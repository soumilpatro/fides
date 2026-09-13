import logging
from datetime import timedelta
from uuid import UUID

import pytest
from app.api.auth import get_client_ip
from app.config import Settings
from app.main import create_app
from app.models.enums import UserStatus
from app.models.user import User

from .test_api import BASE, error, request, signup, verify


def test_openapi_closed_variants_errors_and_bearer():
    schema = create_app().openapi()
    assert {path for path in schema["paths"] if not path.startswith("/api/v1/connections")} == {
        "/health",
        "/readiness",
        "/api/v1/me",
        "/api/v1/me/deactivate",
        *[BASE + suffix for suffix in ["/otp/request", "/otp/verify", "/refresh", "/logout"]],
    }
    for suffix in ["/otp/request", "/otp/verify", "/refresh", "/logout"]:
        operation = schema["paths"][BASE + suffix]["post"]
        assert operation["responses"]["422"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/AuthErrorEnvelope"
        }
        assert "Retry-After" in operation["responses"]["429"]["headers"]
    assert schema["paths"][BASE + "/logout"]["post"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in schema["paths"][BASE + "/refresh"]["post"]
    shapes = schema["components"]["schemas"]
    for name in ["OtpRequest", "SignupOtpVerifyRequest", "LoginOtpVerifyRequest", "RefreshRequest"]:
        assert shapes[name]["additionalProperties"] is False
    assert shapes["OtpRequest"]["properties"]["intent"]["enum"] == ["signup", "login"]
    variants = schema["paths"][BASE + "/otp/verify"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["anyOf"]
    assert {value["$ref"].split("/")[-1] for value in variants} == {
        "SignupOtpVerifyRequest",
        "LoginOtpVerifyRequest",
    }


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"refresh_token": None},
        {"refresh_token": 123},
        {"refresh_token": "bad", "extra": 1},
    ],
)
def test_refresh_closed_json_contract(api, body):
    error(api.client.post(BASE + "/refresh", json=body), "VALIDATION_ERROR", 422)


def test_refresh_query_is_not_a_credential_source(api):
    error(api.client.post(BASE + "/refresh?refresh_token=untrusted"), "VALIDATION_ERROR", 422)


@pytest.mark.parametrize(
    "state,code",
    [
        (UserStatus.DEACTIVATED, "ACCOUNT_DEACTIVATED"),
        (UserStatus.ANONYMIZED, "ACCOUNT_UNAVAILABLE"),
    ],
)
def test_refresh_inactive_account(api, state, code):
    credentials, _ = signup(api)
    with api.factory.begin() as db:
        db.get(User, UUID(credentials["user"]["id"])).status = state
    error(
        api.client.post(BASE + "/refresh", json={"refresh_token": credentials["refresh_token"]}),
        code,
        403,
    )


def test_refresh_expired_and_rate_limited(api):
    credentials, _ = signup(api)
    api.settings.auth_refresh_ip_1m_limit = 1
    error(
        api.client.post(BASE + "/refresh", json={"refresh_token": "bad"}),
        "INVALID_REFRESH_TOKEN",
        401,
    )
    error(
        api.client.post(BASE + "/refresh", json={"refresh_token": credentials["refresh_token"]}),
        "AUTH_RATE_LIMITED",
        429,
    )
    api.clock.now += timedelta(days=30)
    error(
        api.client.post(BASE + "/refresh", json={"refresh_token": credentials["refresh_token"]}),
        "REFRESH_TOKEN_EXPIRED",
        401,
    )


def test_longest_cooldown_and_fixed_window_retry(api):
    api.settings.otp_request_phone_10m_limit = 1
    api.clock.now = api.clock.now.replace(minute=9, second=55)
    assert request(api).status_code == 202
    api.clock.now += timedelta(seconds=1)
    response = request(api, "login")
    error(response, "OTP_RATE_LIMITED", 429)
    assert response.headers["Retry-After"] == "59"


def test_api_ip_default_does_not_trust_forwarded_header(api):
    api.app.dependency_overrides.pop(get_client_ip)
    # TestClient's non-IP peer is rejected; an attacker header cannot replace it.
    error(
        api.client.post(
            BASE + "/otp/request",
            json={"phone": "+14155552671", "intent": "login"},
            headers={"X-Forwarded-For": "192.0.2.1"},
        ),
        "MALFORMED_REQUEST",
        400,
    )


@pytest.mark.parametrize("cidr", ["10.1.2.3/8", "bad", "2001:db8::1/32"])
def test_trusted_proxy_config_rejected_at_startup(cidr):
    with pytest.raises(ValueError):
        Settings(_env_file=None, auth_trusted_proxy_cidrs=[cidr])


def test_logs_hide_failed_profile_otp_and_identity_inputs(api, caplog, monkeypatch):
    # Alembic's fileConfig in db_engine disables existing loggers in this test
    # process; production migrations run separately from the application.
    monkeypatch.setattr(logging.getLogger("fides.auth.challenges"), "disabled", False)
    logging.getLogger().addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG)
    challenge = request(api).json()["challenge_id"]
    error(verify(api, challenge, code="314159", display_name="Private Signup Name"), "OTP_INVALID")
    assert "OTP operation rejected: OTP_INVALID" in caplog.text
    assert all(
        value not in caplog.text for value in ["314159", "Private Signup Name", "+14155552671"]
    )


def test_invalid_profile_still_hits_ip_throttle(api):
    api.settings.otp_verify_ip_1m_limit = 1
    challenge = request(api).json()["challenge_id"]
    error(verify(api, challenge, display_name=""), "VALIDATION_ERROR", 422)
    error(verify(api, challenge, display_name=""), "OTP_RATE_LIMITED", 429)


def test_logout_revokes_only_presented_device_and_expiry_exception_is_restricted(api):
    from app.core.errors import AuthError

    first, _ = signup(api)
    api.clock.now += timedelta(minutes=10)
    login = request(api, "login").json()["challenge_id"]
    second = verify(api, login, "login").json()
    api.clock.now += timedelta(minutes=5)
    with pytest.raises(AuthError, match="AUTH_TOKEN_EXPIRED"):
        api.service.resolve("Bearer " + first["access_token"])
    assert (
        api.client.post(
            BASE + "/logout", json={}, headers={"Authorization": "Bearer " + first["access_token"]}
        ).status_code
        == 200
    )
    assert api.service.resolve("Bearer " + second["access_token"])


def test_quarantined_signup_does_not_block_login_intent(api):
    from app.auth.providers import Outcome, ProviderResult

    api.provider.script(
        "request", "signup", ProviderResult(Outcome.TRANSIENT_FAILURE, uncertain=True)
    )
    error(request(api), "AUTH_PROVIDER_UNAVAILABLE", 503)
    api.clock.now += timedelta(seconds=60)
    assert request(api, "login").status_code == 202


def test_successful_login_does_not_consume_existing_signup_challenge(api):
    signup(api)
    api.clock.now += timedelta(seconds=60)
    signup_challenge = request(api).json()["challenge_id"]
    api.clock.now += timedelta(seconds=60)
    login = request(api, "login").json()["challenge_id"]
    assert verify(api, login, "login").status_code == 200
    error(verify(api, signup_challenge), "AUTH_FLOW_NOT_ALLOWED", 409)


def test_unexpected_provider_exception_is_quarantined_without_diagnostics(api, caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("fides.auth.challenges"), "disabled", False)
    logging.getLogger().addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="fides.auth.challenges")

    async def fail(operation, intent):
        raise RuntimeError("Private provider body 314159")

    api.provider.before_operation = fail
    error(request(api), "AUTH_PROVIDER_UNAVAILABLE", 503)
    assert "OTP operation rejected: AUTH_PROVIDER_UNAVAILABLE" in caplog.text
    assert "Private provider body" not in caplog.text and "314159" not in caplog.text


def test_duplicate_authorization_is_rejected_without_revoking(api):
    credentials, _ = signup(api)
    token = credentials["access_token"]
    response = api.client.post(
        BASE + "/logout",
        headers=[("Authorization", "Bearer " + token), ("Authorization", "Bearer bad")],
    )
    error(response, "INVALID_AUTH_TOKEN", 401)
    assert api.service.resolve("Bearer " + token)


@pytest.mark.parametrize("operation", ["request", "verify"])
def test_locked_challenge_reports_longest_blocking_duration(api, operation):
    api.clock.now = api.clock.now.replace(minute=9, second=50)
    api.settings.otp_request_phone_10m_limit = 1
    api.settings.otp_verify_phone_10m_limit = 5
    challenge = request(api).json()["challenge_id"]
    for _ in range(5):
        error(verify(api, challenge, code="000000"), "OTP_INVALID", 400)
    response = request(api) if operation == "request" else verify(api, challenge)
    error(response, "OTP_RATE_LIMITED", 429)
    assert response.headers["Retry-After"] == "600"


@pytest.mark.parametrize("suffix", ["/otp/request", "/otp/verify", "/refresh", "/logout"])
def test_malformed_json_uses_safe_envelope_on_real_routes(api, suffix):
    response = api.client.post(
        BASE + suffix, content='{"secret":', headers={"Content-Type": "application/json"}
    )
    error(response, "MALFORMED_REQUEST", 400)
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "value",
    [
        "Bearer",
        "Bearer ",
        " Bearer {token}",
        "Bearer {token} ",
        "Bearer  {token}",
        "Bearer {token}, {token}",
        "Bearer\t{token}",
        "Bearer " + "x" * 4096,
        "Basic {token}",
    ],
)
def test_strict_logout_header_rejects_ambiguous_credentials(api, value):
    credentials, _ = signup(api)
    token = credentials["access_token"]
    error(
        api.client.post(BASE + "/logout", headers={"Authorization": value.format(token=token)}),
        "INVALID_AUTH_TOKEN",
        401,
    )
    assert api.service.resolve("Bearer " + token)


def test_refresh_token_cannot_authenticate_logout(api):
    credentials, _ = signup(api)
    error(
        api.client.post(
            BASE + "/logout", headers={"Authorization": "Bearer " + credentials["refresh_token"]}
        ),
        "INVALID_AUTH_TOKEN",
        401,
    )


@pytest.mark.parametrize(
    "peer,forwarded,trusted,expected",
    [
        ("192.0.2.10", "198.51.100.8", (), "192.0.2.10"),
        ("127.0.0.1", "198.51.100.8", (), "127.0.0.1"),
        ("10.0.0.2", "192.0.2.99, 198.51.100.8", ("10.0.0.0/8",), "198.51.100.8"),
        ("10.0.0.2", "bad", ("10.0.0.0/8",), None),
        ("2001:db8::10", "198.51.100.8", (), "2001:db8::10"),
    ],
)
def test_application_resolves_only_explicitly_trusted_forwarding(
    monkeypatch, peer, forwarded, trusted, expected
):
    from app.core.errors import AuthError
    from starlette.requests import Request

    settings = Settings(_env_file=None, auth_trusted_proxy_cidrs=trusted)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: settings)
    incoming = Request(
        {
            "type": "http",
            "client": (peer, 1234),
            "headers": [(b"x-forwarded-for", forwarded.encode())],
        }
    )
    if expected is None:
        with pytest.raises(AuthError, match="MALFORMED_REQUEST"):
            get_client_ip(incoming)
    else:
        assert get_client_ip(incoming) == expected


@pytest.mark.parametrize("exception_kind", ["http", "unexpected"])
def test_real_route_exception_headers_and_privacy(api, monkeypatch, exception_kind, caplog):
    from fastapi import HTTPException

    monkeypatch.setattr(logging.getLogger("fides.errors"), "disabled", False)
    logging.getLogger().addHandler(caplog.handler)
    caplog.set_level(logging.ERROR)

    async def fail(*args, **kwargs):
        if exception_kind == "http":
            raise HTTPException(503, "Private provider diagnostics")
        raise RuntimeError("Private provider diagnostics")

    monkeypatch.setattr(api.challenges, "verify", fail)
    response = api.client.post(
        BASE + "/otp/verify",
        json={"challenge_id": "12345678-1234-1234-1234-123456789abc", "code": "123456"},
        headers={"X-Request-ID": "invalid request id !"},
    )
    error(
        response,
        "HTTP_ERROR" if exception_kind == "http" else "INTERNAL_ERROR",
        503 if exception_kind == "http" else 500,
    )
    assert response.headers["X-Request-ID"] != "invalid request id !"
    assert "Private provider diagnostics" not in response.text + caplog.text
    if exception_kind == "unexpected":
        assert "Unhandled exception while processing request" in caplog.text


def test_documented_runtime_preserves_socket_peer_and_disables_access_logs():
    import shlex
    from pathlib import Path

    from uvicorn.main import main

    readme = (Path(__file__).resolve().parents[3] / "README.md").read_text()
    command = next(line for line in readme.splitlines() if line.startswith("python -m uvicorn "))
    context = main.make_context("uvicorn", shlex.split(command)[3:])
    assert context.params["proxy_headers"] is False
    assert context.params["access_log"] is False


@pytest.mark.parametrize(
    "suffix,body",
    [
        ("/otp/request", {"phone": 14155552671, "intent": "signup"}),
        ("/otp/request", {"phone": "+14155552671", "intent": "signup", "display_name": "Private"}),
        ("/otp/verify", {"challenge_id": "12345678-1234-1234-1234-123456789abc", "code": 123456}),
        ("/otp/verify", {"challenge_id": "12345678-1234-1234-1234-123456789abc", "code": True}),
        ("/refresh", {"refresh_token": True}),
        ("/logout", {"access_token": "private"}),
    ],
)
def test_http_closed_bodies_do_not_coerce_or_accept_alternate_transports(api, suffix, body):
    error(api.client.post(BASE + suffix, json=body), "VALIDATION_ERROR", 422)
