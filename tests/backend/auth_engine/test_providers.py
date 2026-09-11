import asyncio
import base64
import logging
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from app.auth.providers import FakeOtpProvider, Outcome, ProviderResult, build_provider
from app.auth.twilio import TwilioVerifyProvider
from app.config import Settings

SIGNUP = "VA" + "1" * 32
LOGIN = "VA" + "2" * 32
SIGNUP_VE = "VE" + "3" * 32
LOGIN_VE = "VE" + "4" * 32
API_KEY = "SK" + "5" * 32
SECRET = "provider-secret-do-not-log"
PHONE = "+14155552671"
CODE = "314159"


@pytest.fixture
def twilio_settings():
    return Settings(
        _env_file=None,
        app_env="test",
        otp_provider="twilio",
        twilio_api_key_sid=API_KEY,
        twilio_api_key_secret=SECRET,
        twilio_verify_signup_service_sid=SIGNUP,
        twilio_verify_login_service_sid=LOGIN,
        auth_rate_limit_hmac_secret="rate-limit-test-secret",
    )


def test_fake_resend_preserves_expiry_attempts_and_intent(clock):
    async def scenario():
        provider = FakeOtpProvider(clock=clock)
        signup = await provider.request_verification(PHONE, "signup")
        login = await provider.request_verification(PHONE, "login")
        assert (signup.provider_reference, login.provider_reference) == (
            "fake-signup-1",
            "fake-login-2",
        )
        assert signup.provider_key == "fake_signup" and login.provider_key == "fake_login"
        assert (
            await provider.verify_code(signup.provider_reference, "000000", "signup")
        ).outcome == Outcome.INVALID_CODE
        clock.now += timedelta(seconds=599)
        assert await provider.request_verification(PHONE, "signup") == signup
        assert (
            await provider.verify_code(signup.provider_reference, "123456", "login")
        ).outcome == Outcome.CHALLENGE_UNAVAILABLE
        assert (
            await provider.verify_stored(signup.provider_key, signup.provider_reference, "123456")
        ).outcome == Outcome.APPROVED
        assert (
            await provider.verify_code(signup.provider_reference, "123456", "signup")
        ).outcome == Outcome.CHALLENGE_UNAVAILABLE
        assert (
            await provider.verify_code(login.provider_reference, "654321", "login")
        ).outcome == Outcome.APPROVED
        replacement = await provider.request_verification(PHONE, "signup")
        clock.now += timedelta(seconds=600)
        assert (
            await provider.verify_code(replacement.provider_reference, "123456", "signup")
        ).outcome == Outcome.EXPIRED
        assert (
            await provider.request_verification(PHONE, "signup")
        ).provider_reference != replacement.provider_reference

    asyncio.run(scenario())


def test_fake_fifth_attempt_can_succeed_resend_cannot_reset_exhaustion(clock):
    async def scenario():
        provider = FakeOtpProvider(clock=clock)
        for intent, correct in provider.TEST_CODES.items():
            result = await provider.request_verification(PHONE, intent)
            for _ in range(4):
                assert (
                    await provider.verify_code(result.provider_reference, "000000", intent)
                ).outcome == Outcome.INVALID_CODE
            assert await provider.request_verification(PHONE, intent) == result
            fifth = correct if intent == "signup" else "000000"
            assert (
                await provider.verify_code(result.provider_reference, fifth, intent)
            ).outcome == (Outcome.APPROVED if intent == "signup" else Outcome.INVALID_CODE)
            if intent == "login":
                assert (
                    await provider.request_verification(PHONE, intent)
                ).outcome == Outcome.RATE_LIMITED
                assert (
                    await provider.verify_code(result.provider_reference, correct, intent)
                ).outcome == Outcome.RATE_LIMITED

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "outcome",
    [
        Outcome.RATE_LIMITED,
        Outcome.DELIVERY_UNAVAILABLE,
        Outcome.TRANSIENT_FAILURE,
        Outcome.CONFIGURATION_FAILURE,
        Outcome.CHALLENGE_UNAVAILABLE,
    ],
)
def test_fake_scripted_failure_uncertainty(outcome, clock, caplog):
    async def scenario():
        provider = FakeOtpProvider(clock=clock)
        expected = ProviderResult(outcome, uncertain=True)
        provider.script("request", "signup", expected)
        provider.script("verify", "signup", expected)
        assert await provider.request_verification(PHONE, "signup") == expected
        challenge = await provider.request_verification(PHONE, "signup")
        assert await provider.verify_code(challenge.provider_reference, CODE, "signup") == expected
        assert (await provider.request_verification(PHONE, "login")).outcome == Outcome.REQUESTED
        assert (
            await provider.verify_stored("wrong-route", "opaque", CODE)
        ).outcome == Outcome.CONFIGURATION_FAILURE
        assert CODE not in repr(expected) + repr(provider) + caplog.text

    asyncio.run(scenario())


def test_fake_concurrent_checks_single_use(clock):
    async def scenario():
        gate = asyncio.Event()
        arrived = 0

        async def before(operation, intent):
            nonlocal arrived
            if operation == "verify":
                arrived += 1
                if arrived == 2:
                    gate.set()
                await asyncio.wait_for(gate.wait(), 2)

        provider = FakeOtpProvider(clock=clock, before_operation=before)
        requested = await provider.request_verification(PHONE, "signup")
        results = await asyncio.gather(
            *[
                provider.verify_code(requested.provider_reference, "123456", "signup")
                for _ in range(2)
            ]
        )
        assert {result.outcome for result in results} == {
            Outcome.APPROVED,
            Outcome.CHALLENGE_UNAVAILABLE,
        }

    asyncio.run(scenario())


def test_explicit_provider_selection_no_production_fallback(settings, twilio_settings):
    assert isinstance(build_provider(settings), FakeOtpProvider)
    with pytest.raises(ValueError):
        build_provider(Settings(_env_file=None, app_env="test", otp_provider="disabled"))
    with pytest.raises(ValueError):
        # Even bypassing Settings validation cannot enable a production fake fallback.
        build_provider(settings.model_copy(update={"app_env": "production"}))
    with pytest.raises(ValueError):
        TwilioVerifyProvider(settings)


def test_twilio_dual_service_wire_contract_single_use_no_fallback(twilio_settings):
    requests, consumed = [], set()

    def handle(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.scheme == "https" and request.url.host == "verify.twilio.com"
        assert request.url.path.startswith("/v2/Services/")
        assert (
            request.headers["Authorization"]
            == "Basic " + base64.b64encode(f"{API_KEY}:{SECRET}".encode()).decode()
        )
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        service = request.url.path.split("/")[-2]
        sid = {SIGNUP: SIGNUP_VE, LOGIN: LOGIN_VE}[service]
        data = parse_qs(request.content.decode())
        if request.url.path.endswith("/Verifications"):
            assert data == {"To": [PHONE], "Channel": ["sms"]}
            status = "pending"
        else:
            assert request.url.path.endswith("/VerificationCheck")
            assert set(data) == {"VerificationSid", "Code"} and data["Code"] == [CODE]
            if data["VerificationSid"] != [sid] or sid in consumed:
                return httpx.Response(404, json={"status": "approved"})
            consumed.add(sid)
            status = "approved"
        return httpx.Response(200, json={"sid": sid, "service_sid": service, "status": status})

    async def scenario():
        provider = build_provider(twilio_settings, transport=httpx.MockTransport(handle))
        try:
            signup = await provider.request_verification(PHONE, "signup")
            login = await provider.request_verification(PHONE, "login")
            assert signup.provider_reference == SIGNUP_VE and login.provider_reference == LOGIN_VE
            assert signup.provider_key == "twilio_verify_v2_signup"
            assert login.provider_key == "twilio_verify_v2_login"
            mismatch = await provider.verify_stored(
                login.provider_key, signup.provider_reference, CODE
            )
            assert mismatch.outcome == Outcome.CHALLENGE_UNAVAILABLE
            for result in [signup, login]:
                assert (
                    await provider.verify_stored(
                        result.provider_key, result.provider_reference, CODE
                    )
                ).outcome == Outcome.APPROVED
                assert (
                    await provider.verify_stored(
                        result.provider_key, result.provider_reference, CODE
                    )
                ).outcome == Outcome.CHALLENGE_UNAVAILABLE
            assert (
                await provider.verify_stored("unknown", SIGNUP_VE, CODE)
            ).outcome == Outcome.CONFIGURATION_FAILURE
            assert len(requests) == 7  # no retry/fallback request for any rejection
        finally:
            await provider.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "checking,http_status,body,expected,uncertain",
    [
        (True, 200, {"status": "approved"}, Outcome.APPROVED, False),
        (True, 200, {"status": "pending", "valid": True}, Outcome.INVALID_CODE, False),
        (True, 200, {"status": "expired"}, Outcome.EXPIRED, False),
        (True, 200, {"status": "max_attempts_reached"}, Outcome.RATE_LIMITED, False),
        (True, 200, {"status": "deleted"}, Outcome.CHALLENGE_UNAVAILABLE, False),
        (True, 200, {"status": "canceled"}, Outcome.CHALLENGE_UNAVAILABLE, False),
        (True, 200, {"status": "failed"}, Outcome.CHALLENGE_UNAVAILABLE, False),
        (True, 200, {"status": "unknown", "valid": True}, Outcome.CHALLENGE_UNAVAILABLE, True),
        (True, 200, {"status": "approved", "sid": LOGIN_VE}, Outcome.CHALLENGE_UNAVAILABLE, True),
        (
            True,
            200,
            {"status": "approved", "service_sid": LOGIN},
            Outcome.CHALLENGE_UNAVAILABLE,
            True,
        ),
        (True, 200, {"status": "approved", "sid": "bad"}, Outcome.TRANSIENT_FAILURE, True),
        (True, 404, {"status": "approved", "valid": True}, Outcome.CHALLENGE_UNAVAILABLE, False),
        (True, 429, {}, Outcome.RATE_LIMITED, False),
        (True, 400, {"code": 60202}, Outcome.RATE_LIMITED, False),
        (True, 400, {"code": 60200}, Outcome.CONFIGURATION_FAILURE, False),
        (True, 401, {}, Outcome.CONFIGURATION_FAILURE, False),
        (True, 403, {}, Outcome.CONFIGURATION_FAILURE, False),
        (True, 503, {"status": "approved"}, Outcome.TRANSIENT_FAILURE, True),
        (True, 302, {"status": "approved"}, Outcome.TRANSIENT_FAILURE, True),
        (False, 201, {"status": "pending"}, Outcome.REQUESTED, False),
        (False, 201, {"status": "approved"}, Outcome.TRANSIENT_FAILURE, True),
        (False, 201, {"status": "failed"}, Outcome.DELIVERY_UNAVAILABLE, False),
        (False, 201, {"status": "max_attempts_reached"}, Outcome.RATE_LIMITED, False),
        (False, 400, {"code": 60205}, Outcome.DELIVERY_UNAVAILABLE, False),
        (False, 400, {"code": 60203}, Outcome.RATE_LIMITED, False),
        (False, 404, {}, Outcome.CONFIGURATION_FAILURE, False),
        (False, 500, {}, Outcome.TRANSIENT_FAILURE, True),
        (False, 503, {"code": 60203}, Outcome.TRANSIENT_FAILURE, True),
        (True, 502, {"code": 60202}, Outcome.TRANSIENT_FAILURE, True),
    ],
)
def test_twilio_normalized_results(
    twilio_settings, checking, http_status, body, expected, uncertain, caplog
):
    caplog.set_level(logging.DEBUG)
    calls = []

    def handle(request):
        calls.append(request)
        # Emulate potentially sensitive library DEBUG diagnostics before handlers.
        logging.getLogger("httpcore.http11").debug("headers %s body %s", SECRET, CODE)
        return httpx.Response(
            http_status,
            json={
                "sid": SIGNUP_VE,
                "service_sid": SIGNUP,
                "message": SECRET + PHONE + CODE,
                **body,
            },
            headers={"Retry-After": "17"},
        )

    async def scenario():
        provider = TwilioVerifyProvider(twilio_settings, transport=httpx.MockTransport(handle))
        try:
            result = await (
                provider.verify_code(SIGNUP_VE, CODE, "signup")
                if checking
                else provider.request_verification(PHONE, "signup")
            )
            assert result.outcome == expected and result.uncertain == uncertain
            if http_status == 429:
                assert result.retry_after_seconds == 17
            assert len(calls) == 1
            for secret in [SECRET, PHONE, CODE, "Authorization", SIGNUP_VE]:
                assert secret not in caplog.text + repr(result)
        finally:
            await provider.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.RemoteProtocolError,
    ],
)
def test_twilio_transport_failure_uncertain_no_retry(twilio_settings, error_type, caplog):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.extensions["timeout"] == {"connect": 2, "read": 5, "write": 5, "pool": 1}
        raise error_type(SECRET + CODE + PHONE)

    async def scenario():
        provider = TwilioVerifyProvider(twilio_settings, transport=httpx.MockTransport(handle))
        try:
            result = await provider.verify_code(SIGNUP_VE, CODE, "signup")
            assert result.outcome == Outcome.TRANSIENT_FAILURE and result.uncertain
            assert len(calls) == 1
            assert SECRET not in caplog.text and CODE not in caplog.text
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_overall_budget_cancels_hung_transport(twilio_settings):
    calls = []

    async def handle(request):
        calls.append(request)
        await asyncio.Event().wait()

    async def scenario():
        provider = TwilioVerifyProvider(twilio_settings, transport=httpx.MockTransport(handle))
        provider._budget = 0.01  # bounded timer test, no sleep or live socket
        try:
            result = await provider.request_verification(PHONE, "signup")
            assert result.outcome == Outcome.TRANSIENT_FAILURE and result.uncertain
            assert len(calls) == 1
        finally:
            await provider.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("content", [b"not json", b"null", b"[]", b"{}", b'{"status":"approved"}'])
def test_twilio_ambiguous_body_never_approves(twilio_settings, content):
    async def scenario():
        provider = TwilioVerifyProvider(
            twilio_settings,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content)),
        )
        try:
            result = await provider.verify_code(SIGNUP_VE, CODE, "signup")
            assert result.outcome == Outcome.TRANSIENT_FAILURE and result.uncertain
        finally:
            await provider.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [None, [], {}, 1, True])
def test_malformed_status_fails_closed(twilio_settings, value):
    async def scenario():
        provider = TwilioVerifyProvider(
            twilio_settings,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "sid": SIGNUP_VE,
                        "service_sid": SIGNUP,
                        "status": value,
                    },
                )
            ),
        )
        try:
            result = await provider.verify_code(SIGNUP_VE, CODE, "signup")
            assert result.outcome == Outcome.TRANSIENT_FAILURE and result.uncertain
        finally:
            await provider.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("code", [123456, "12345", "1234567", "١٢٣٤٥٦", "123456\n", None])
def test_bad_otp_never_calls_provider(twilio_settings, code):
    def forbidden(request):
        raise AssertionError("Malformed OTP must not reach the transport")

    async def scenario():
        provider = TwilioVerifyProvider(twilio_settings, transport=httpx.MockTransport(forbidden))
        try:
            assert (
                await provider.verify_code(SIGNUP_VE, code, "signup")
            ).outcome == Outcome.INVALID_CODE
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_fake_resend_does_not_extend_pending_deadline(clock):
    async def scenario():
        provider = FakeOtpProvider(clock=clock)
        challenge = await provider.request_verification(PHONE, "signup")
        clock.now += timedelta(seconds=599)
        assert await provider.request_verification(PHONE, "signup") == challenge
        clock.now += timedelta(seconds=1)
        assert (
            await provider.verify_code(challenge.provider_reference, "123456", "signup")
        ).outcome == Outcome.EXPIRED

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", [Outcome.APPROVED, Outcome.REQUESTED])
@pytest.mark.parametrize("missing", ["reference", "route", "uncertain"])
def test_provider_success_cannot_be_ambiguous(outcome, missing):
    with pytest.raises(ValueError, match="identified challenge"):
        ProviderResult(
            outcome,
            None if missing == "reference" else "opaque",
            None if missing == "route" else "fake_signup",
            uncertain=missing == "uncertain",
        )


@pytest.mark.parametrize("outcome", [Outcome.APPROVED, Outcome.REQUESTED])
def test_fake_script_cannot_fabricate_success(clock, outcome):
    provider = FakeOtpProvider(clock=clock)
    with pytest.raises(ValueError, match="state machine"):
        provider.script("verify", "signup", ProviderResult(outcome, "missing", "fake_signup"))


def test_fake_failures_consume_attempts_and_cannot_override_terminal_state(clock):
    async def scenario():
        provider = FakeOtpProvider(clock=clock)
        signup = await provider.request_verification(PHONE, "signup")
        login = await provider.request_verification(PHONE, "login")
        failure = ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
        provider.script("verify", "signup", *[failure for _ in range(6)])
        assert (
            await provider.verify_code(login.provider_reference, "123456", "signup")
        ).outcome == Outcome.CHALLENGE_UNAVAILABLE
        assert (
            await provider.verify_code("missing", "123456", "signup")
        ).outcome == Outcome.CHALLENGE_UNAVAILABLE
        for _ in range(5):
            assert (
                await provider.verify_code(signup.provider_reference, "123456", "signup") == failure
            )
        assert (
            await provider.verify_code(signup.provider_reference, "123456", "signup")
        ).outcome == Outcome.RATE_LIMITED
        assert (
            await provider.verify_code(login.provider_reference, "654321", "login")
        ).outcome == Outcome.APPROVED
        provider.script("verify", "login", failure)
        assert (
            await provider.verify_code(login.provider_reference, "654321", "login")
        ).outcome == Outcome.CHALLENGE_UNAVAILABLE
        clock.now += timedelta(minutes=10)
        assert (
            await provider.verify_code(signup.provider_reference, "123456", "signup")
        ).outcome == Outcome.EXPIRED

    asyncio.run(scenario())


@pytest.mark.parametrize("checking", [False, True])
@pytest.mark.parametrize(
    "sid", [None, "", "VE" + "g" * 32, "VE" + "3" * 31, "VE" + "3" * 32 + "\n"]
)
def test_twilio_missing_or_malformed_reference_fails_closed(twilio_settings, checking, sid):
    async def scenario():
        provider = TwilioVerifyProvider(
            twilio_settings,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "sid": sid,
                        "service_sid": SIGNUP,
                        "status": "approved" if checking else "pending",
                    },
                )
            ),
        )
        try:
            result = await (
                provider.verify_code(SIGNUP_VE, CODE, "signup")
                if checking
                else provider.request_verification(PHONE, "signup")
            )
            assert result.outcome == Outcome.TRANSIENT_FAILURE and result.uncertain
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_twilio_client_is_reused_and_transport_closed(twilio_settings):
    class Transport(httpx.AsyncBaseTransport):
        calls = 0
        closed = False

        async def handle_async_request(self, request):
            self.calls += 1
            return httpx.Response(
                200,
                json={
                    "sid": SIGNUP_VE,
                    "service_sid": SIGNUP,
                    "status": "pending",
                },
            )

        async def aclose(self):
            self.closed = True

    async def scenario():
        transport = Transport()
        provider = build_provider(twilio_settings, transport=transport)
        try:
            for _ in range(2):
                assert (
                    await provider.request_verification(PHONE, "signup")
                ).outcome == Outcome.REQUESTED
            assert transport.calls == 2 and not transport.closed
        finally:
            await provider.aclose()
        assert transport.closed
        await FakeOtpProvider().aclose()

    asyncio.run(scenario())
