from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.auth.providers import Outcome, ProviderResult
from app.models.audit_log import AuditLog
from app.models.auth_identity import AuthIdentity
from app.models.auth_otp_challenge import AuthOtpChallenge
from app.models.auth_rate_limit_bucket import AuthRateLimitBucket
from app.models.auth_session import AuthSession
from app.models.enums import UserStatus
from app.models.user import User
from sqlalchemy import select

PHONE = "+14155552671"
BASE = "/api/v1/auth"


def request(api, intent="signup"):
    return api.client.post(BASE + "/otp/request", json={"phone": PHONE, "intent": intent})


def verify(api, challenge, intent="signup", code=None, **profile):
    body = {"challenge_id": challenge, "code": code or api.provider.TEST_CODES[intent]}
    if intent == "signup":
        body.update(display_name=" Example ", timezone=" UTC ")
        body.update(profile)
    return api.client.post(BASE + "/otp/verify", json=body)


def signup(api):
    challenge = request(api).json()["challenge_id"]
    result = verify(api, challenge)
    assert result.status_code == 200, result.text
    return result.json(), challenge


def error(response, code, status=None):
    assert response.json()["error"]["code"] == code, response.text
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message"}
    if status:
        assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]
    if response.status_code == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"
    if response.status_code == 429:
        assert int(response.headers["Retry-After"]) >= 0


def test_signup_exact_rows_response_audit_and_replay(api):
    result, challenge = signup(api)
    assert set(result) == {
        "access_token",
        "refresh_token",
        "token_type",
        "access_expires_at",
        "refresh_expires_at",
        "user",
    }
    assert result["token_type"] == "Bearer" and result["access_expires_at"].endswith("Z")
    assert result["user"]["display_name"] == "Example" and result["user"]["timezone"] == "UTC"
    with api.factory() as db:
        user = db.get(User, UUID(result["user"]["id"]))
        assert user.status == UserStatus.ACTIVE and user.deactivated_at is None
        assert user.created_at == user.updated_at == api.clock.now
        identity = db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == user.id))
        assert (identity.provider, identity.provider_subject, identity.verified_at) == (
            "phone",
            PHONE,
            api.clock.now,
        )
        assert db.get(AuthOtpChallenge, UUID(challenge)).state == "CONSUMED"
        audits = db.scalars(select(AuditLog).where(AuditLog.actor_user_id == user.id)).all()
        assert {item.action for item in audits} == {
            "AUTH_OTP_VERIFIED",
            "ACCOUNT_CREATED",
            "AUTH_SESSION_CREATED",
        }
        assert len(audits) == 3
        for item in audits:
            assert not any(
                value in str(item.metadata_) for value in [PHONE, result["access_token"], "Example"]
            )
    error(verify(api, challenge), "OTP_REPLAYED", 409)


def test_request_resend_cross_intent_and_cooldown(api):
    first = request(api)
    assert first.status_code == 202
    original = first.json()
    assert set(original) == {"challenge_id", "expires_at", "resend_after_seconds", "message"}
    assert original["message"] == "Verification requested."
    error(request(api, "login"), "OTP_RATE_LIMITED", 429)
    api.clock.now += timedelta(seconds=60)
    second = request(api, "login")
    assert second.status_code == 202
    assert second.json()["challenge_id"] != original["challenge_id"]
    # Counted throttled request used the third allowance. Move into a new fixed window.
    api.clock.now += timedelta(seconds=540)
    # First challenge is now expired, so a replacement receives a new UUID.
    replacement = request(api)
    assert replacement.status_code == 202
    assert replacement.json()["challenge_id"] != original["challenge_id"]


def test_resend_preserves_identity_expiry_and_attempts(api):
    first = request(api).json()
    error(verify(api, first["challenge_id"], code="000000"), "OTP_INVALID")
    api.clock.now += timedelta(seconds=60)
    resent = request(api).json()
    assert resent["challenge_id"] == first["challenge_id"]
    assert resent["expires_at"] == first["expires_at"]
    with api.factory() as db:
        assert db.get(AuthOtpChallenge, UUID(first["challenge_id"])).verify_attempts == 1


def test_independent_login_issued_before_signup_succeeds_after_signup(api):
    login = request(api, "login").json()["challenge_id"]
    api.clock.now += timedelta(seconds=60)
    credentials, signup_id = signup(api)
    login_result = verify(api, login, "login")
    assert login_result.status_code == 200
    assert login_result.json()["user"] == credentials["user"]
    assert login_result.json()["access_token"] != credentials["access_token"]
    with api.factory() as db:
        assert all(
            db.get(AuthOtpChallenge, UUID(value)).state == "CONSUMED"
            for value in [login, signup_id]
        )
        assert (
            len(
                db.scalars(
                    select(AuthSession).where(
                        AuthSession.user_id == UUID(credentials["user"]["id"])
                    )
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize(
    "state", [None, UserStatus.ACTIVE, UserStatus.DEACTIVATED, UserStatus.ANONYMIZED]
)
@pytest.mark.parametrize("intent", ["signup", "login"])
def test_enumeration_safe_request_and_post_proof_eligibility(api, state, intent):
    if state:
        user_id = api.user()
        with api.factory.begin() as db:
            user = db.get(User, user_id)
            user.phone_e164, user.status = PHONE, state
            db.add(
                AuthIdentity(
                    user_id=user_id,
                    provider="phone",
                    provider_subject=PHONE,
                    verified_at=api.clock.now,
                )
            )
    response = request(api, intent)
    assert response.status_code == 202 and response.json()["message"] == "Verification requested."
    proof = verify(api, response.json()["challenge_id"], intent)
    if (state is None and intent == "signup") or (state == UserStatus.ACTIVE and intent == "login"):
        assert proof.status_code == 200, proof.text
    else:
        code = (
            "ACCOUNT_DEACTIVATED"
            if state == UserStatus.DEACTIVATED
            else (
                "ACCOUNT_UNAVAILABLE" if state == UserStatus.ANONYMIZED else "AUTH_FLOW_NOT_ALLOWED"
            )
        )
        error(proof, code)
        with api.factory() as db:
            challenge = db.get(AuthOtpChallenge, UUID(response.json()["challenge_id"]))
            assert challenge.state == "CONSUMED"
            assert (
                db.scalar(
                    select(AuditLog).where(
                        AuditLog.object_id == challenge.id,
                        AuditLog.action == "AUTH_ACCOUNT_ACCESS_DENIED",
                    )
                ).result
                == "DENIED"
            )


def test_identity_inconsistency_denied_after_proof(api):
    user_id = api.user()
    with api.factory.begin() as db:
        db.get(User, user_id).phone_e164 = PHONE
    challenge = request(api, "login").json()["challenge_id"]
    error(verify(api, challenge, "login"), "SERVICE_UNAVAILABLE", 503)


@pytest.mark.parametrize(
    "profile",
    [{"display_name": " "}, {"timezone": "unknown"}, {"display_name": None}, {"timezone": None}],
)
def test_invalid_profile_counts_ip_without_provider_or_attempt(api, profile):
    calls = []

    async def observe(operation, intent):
        calls.append(operation)

    api.provider.before_operation = observe
    challenge = request(api).json()["challenge_id"]
    error(verify(api, challenge, **profile), "VALIDATION_ERROR", 422)
    assert calls == ["request"]
    with api.factory() as db:
        assert db.get(AuthOtpChallenge, UUID(challenge)).verify_attempts == 0
        assert (
            db.scalar(
                select(AuthRateLimitBucket.request_count).where(
                    AuthRateLimitBucket.policy == "otp_verify_ip_1m",
                    AuthRateLimitBucket.subject_hash == api.limiter.subject("ip", "192.0.2.1"),
                )
            )
            == 1
        )


@pytest.mark.parametrize("intent", ["signup", "login"])
def test_stored_intent_controls_variant(api, intent):
    challenge = request(api, intent).json()["challenge_id"]
    error(
        verify(api, challenge, "login" if intent == "signup" else "signup"), "VALIDATION_ERROR", 422
    )
    with api.factory() as db:
        assert db.get(AuthOtpChallenge, UUID(challenge)).verify_attempts == 0


def test_attempt_exhaustion_and_expiry(api):
    calls = []

    async def observe(operation, intent):
        calls.append(operation)

    api.provider.before_operation = observe
    challenge = request(api).json()["challenge_id"]
    for _ in range(5):
        error(verify(api, challenge, code="000000"), "OTP_INVALID", 400)
    error(verify(api, challenge), "OTP_RATE_LIMITED", 429)
    assert calls.count("verify") == 5
    api.clock.now += timedelta(minutes=10)
    error(verify(api, challenge), "OTP_EXPIRED", 400)


@pytest.mark.parametrize(
    "outcome,uncertain,error_code,state",
    [
        (Outcome.RATE_LIMITED, False, "OTP_RATE_LIMITED", "FAILED"),
        (Outcome.DELIVERY_UNAVAILABLE, False, "OTP_DELIVERY_UNAVAILABLE", "FAILED"),
        (Outcome.CONFIGURATION_FAILURE, False, "AUTH_PROVIDER_UNAVAILABLE", "FAILED"),
        (Outcome.TRANSIENT_FAILURE, True, "AUTH_PROVIDER_UNAVAILABLE", "INDETERMINATE"),
    ],
)
def test_provider_request_failures(api, outcome, uncertain, error_code, state):
    api.provider.script("request", "signup", ProviderResult(outcome, uncertain=uncertain))
    error(request(api), error_code)
    with api.factory() as db:
        row = db.scalar(select(AuthOtpChallenge).where(AuthOtpChallenge.phone_e164 == PHONE))
        assert row.state == state
        assert row.operation_id is None


@pytest.mark.parametrize(
    "outcome,uncertain,error_code,state",
    [
        (Outcome.EXPIRED, False, "OTP_EXPIRED", "EXPIRED"),
        (Outcome.RATE_LIMITED, False, "OTP_RATE_LIMITED", "LOCKED"),
        (Outcome.CHALLENGE_UNAVAILABLE, False, "OTP_CHALLENGE_UNAVAILABLE", "INDETERMINATE"),
        (Outcome.CONFIGURATION_FAILURE, False, "AUTH_PROVIDER_UNAVAILABLE", "PENDING"),
        (Outcome.TRANSIENT_FAILURE, True, "AUTH_PROVIDER_UNAVAILABLE", "INDETERMINATE"),
    ],
)
def test_provider_verify_failures(api, outcome, uncertain, error_code, state):
    challenge = request(api).json()["challenge_id"]
    api.provider.script("verify", "signup", ProviderResult(outcome, uncertain=uncertain))
    error(verify(api, challenge), error_code)
    with api.factory() as db:
        row = db.get(AuthOtpChallenge, UUID(challenge))
        assert row.state == state and row.verify_attempts == 1


def test_unknown_challenge(api):
    error(verify(api, str(uuid4()), "login"), "OTP_INVALID_CHALLENGE", 400)


def test_refresh_logout_and_headers(api):
    original, _ = signup(api)
    response = api.client.post(
        BASE + "/refresh",
        json={"refresh_token": original["refresh_token"]},
        headers={"X-Request-ID": "review-123"},
    )
    assert response.status_code == 200 and response.headers["X-Request-ID"] == "review-123"
    assert response.headers["Cache-Control"] == "no-store"
    rotated = response.json()
    error(
        api.client.post(BASE + "/refresh", json={"refresh_token": original["refresh_token"]}),
        "INVALID_REFRESH_TOKEN",
    )
    error(
        api.client.post(
            BASE + "/logout", headers={"Authorization": "Bearer " + original["access_token"]}
        ),
        "INVALID_AUTH_TOKEN",
    )
    api.clock.now += timedelta(minutes=15)
    logout = api.client.post(
        BASE + "/logout", headers={"Authorization": "Bearer " + rotated["access_token"]}
    )
    assert logout.status_code == 200 and logout.json() == {"logged_out": True}
    error(
        api.client.post(BASE + "/refresh", json={"refresh_token": rotated["refresh_token"]}),
        "SESSION_REVOKED",
    )
    error(
        api.client.post(
            BASE + "/logout", headers={"Authorization": "Bearer " + rotated["access_token"]}
        ),
        "SESSION_REVOKED",
    )


@pytest.mark.parametrize(
    "body,code",
    [("null", "VALIDATION_ERROR"), ('{"x":1}', "VALIDATION_ERROR"), ("{", "MALFORMED_REQUEST")],
)
def test_logout_body_contract(api, body, code):
    error(
        api.client.post(
            BASE + "/logout", content=body, headers={"Content-Type": "application/json"}
        ),
        code,
    )


@pytest.mark.parametrize(
    "header,code",
    [
        (None, "AUTH_REQUIRED"),
        ("Bearer bad", "INVALID_AUTH_TOKEN"),
        ("Basic xx", "INVALID_AUTH_TOKEN"),
    ],
)
def test_logout_auth_errors(api, header, code):
    error(
        api.client.post(
            BASE + "/logout", json={}, headers={"Authorization": header} if header else {}
        ),
        code,
        401,
    )


def test_fifth_provider_check_can_succeed_and_preserves_leading_zeroes(api):
    api.provider.TEST_CODES = {"signup": "000123", "login": "654321"}
    challenge = request(api).json()["challenge_id"]
    for _ in range(4):
        error(verify(api, challenge, code="000000"), "OTP_INVALID", 400)
    assert verify(api, challenge, code="000123").status_code == 200
    error(verify(api, challenge, code="000123"), "OTP_REPLAYED", 409)
    with api.factory() as db:
        assert db.get(AuthOtpChallenge, UUID(challenge)).verify_attempts == 5


@pytest.mark.parametrize("corruption", ["unverified", "conflicting", "identity_only"])
def test_identity_integrity_never_repaired_or_adopted(api, corruption):
    user_id = api.user()
    with api.factory.begin() as db:
        user = db.get(User, user_id)
        if corruption != "identity_only":
            user.phone_e164 = PHONE
        identity_user = api.user() if corruption == "conflicting" else user_id
        db.add(
            AuthIdentity(
                user_id=identity_user,
                provider="phone",
                provider_subject=PHONE,
                verified_at=None if corruption == "unverified" else api.clock.now,
            )
        )
    challenge = request(api, "login").json()["challenge_id"]
    error(verify(api, challenge, "login"), "SERVICE_UNAVAILABLE", 503)
    with api.factory() as db:
        identities = db.scalars(
            select(AuthIdentity).where(AuthIdentity.provider_subject == PHONE)
        ).all()
        assert len(identities) == 1 and identities[0].user_id == identity_user
        assert identities[0].verified_at == (None if corruption == "unverified" else api.clock.now)
        assert not db.scalars(
            select(AuthSession).where(AuthSession.user_id.in_([user_id, identity_user]))
        ).all()


@pytest.mark.parametrize("mismatch", ["reference", "route"])
def test_nonmatching_approval_never_authorizes_account(api, monkeypatch, mismatch):
    challenge = request(api).json()["challenge_id"]

    async def wrong_approval(key, reference, code):
        return ProviderResult(
            Outcome.APPROVED,
            "other-reference" if mismatch == "reference" else reference,
            "fake_login" if mismatch == "route" else key,
        )

    monkeypatch.setattr(api.provider, "verify_stored", wrong_approval)
    error(verify(api, challenge), "OTP_CHALLENGE_UNAVAILABLE", 409)
    with api.factory() as db:
        assert db.get(AuthOtpChallenge, UUID(challenge)).state == "INDETERMINATE"
        assert db.scalar(select(User).where(User.phone_e164 == PHONE)) is None
