from datetime import timedelta
from uuid import uuid4

import pytest
from app.auth.maintenance import cleanup_auth
from app.auth.tokens import generate_token, token_digest
from app.core.errors import AuthError
from app.models.audit_log import AuditLog
from app.models.auth_identity import AuthIdentity
from app.models.auth_otp_challenge import AuthOtpChallenge
from app.models.auth_rate_limit_bucket import AuthRateLimitBucket
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.enums import CommitmentStatus
from app.models.user import User
from auth_api.test_api import PHONE, error, verify
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError


@pytest.fixture
def retention_rows(account):
    api = account.api
    rows = []
    with api.factory.begin() as db:
        for index, offset in enumerate((-1, 0, 1)):
            expiry = api.clock.now - timedelta(hours=24) + timedelta(microseconds=offset)
            challenge_id, session_id = uuid4(), uuid4()
            db.add(
                AuthOtpChallenge(
                    id=challenge_id,
                    phone_e164=PHONE,
                    intent="signup",
                    state="FAILED",
                    provider_key="fake_signup",
                    created_at=expiry - timedelta(minutes=10),
                    expires_at=expiry,
                    last_requested_at=expiry - timedelta(minutes=10),
                )
            )
            subject = api.limiter.subject("ip", f"192.0.2.{index + 100}")
            policy = f"retention_test_{index}"
            db.add(
                AuthRateLimitBucket(
                    policy=policy,
                    subject_hash=subject,
                    request_count=1,
                    window_started_at=expiry - timedelta(minutes=10),
                    expires_at=expiry,
                )
            )
            refresh_expiry = api.clock.now - timedelta(days=30) + timedelta(microseconds=offset)
            created = refresh_expiry - timedelta(days=30)
            access, refresh = generate_token("access"), generate_token("refresh")
            db.add(
                AuthSession(
                    id=session_id,
                    user_id=account.user_id,
                    access_token_hash=token_digest(access, "access"),
                    refresh_token_hash=token_digest(refresh, "refresh"),
                    created_at=created,
                    access_expires_at=created + timedelta(minutes=15),
                    refresh_expires_at=refresh_expiry,
                )
            )
            rows.append((challenge_id, session_id, policy, access))
    return rows


def test_exact_retention_cutoffs_preserve_accounts_identity_audit_and_financial_history(
    account, retention_rows
):
    api = account.api
    commitment_id = account.commitment(CommitmentStatus.CLOSED)
    with api.factory() as db:
        original_audits = set(
            db.scalars(select(AuditLog.id).where(AuditLog.actor_user_id == account.user_id))
        )
        identity_id = db.scalar(
            select(AuthIdentity.id).where(AuthIdentity.user_id == account.user_id)
        )
    counts = cleanup_auth(api.factory, api.settings, clock=api.clock)
    assert counts == {"auth_otp_challenges": 2, "auth_rate_limit_buckets": 2, "auth_sessions": 2}
    with api.factory() as db:
        for index, (challenge_id, session_id, policy, _) in enumerate(retention_rows):
            assert (db.get(AuthOtpChallenge, challenge_id) is not None) == (index == 2)
            assert (db.get(AuthSession, session_id) is not None) == (index == 2)
            assert (
                db.scalar(
                    select(AuthRateLimitBucket.policy).where(AuthRateLimitBucket.policy == policy)
                )
                is not None
            ) == (index == 2)
        assert db.get(User, account.user_id).phone_e164 == PHONE
        assert db.get(AuthIdentity, identity_id).provider_subject == PHONE
        assert db.get(Commitment, commitment_id).status == CommitmentStatus.CLOSED
        assert (
            set(db.scalars(select(AuditLog.id).where(AuditLog.actor_user_id == account.user_id)))
            == original_audits
        )
    assert api.service.resolve(account.headers["Authorization"])
    with pytest.raises(AuthError, match="INVALID_AUTH_TOKEN"):
        api.service.resolve("Bearer " + retention_rows[0][3])
    error(verify(api, str(retention_rows[0][0])), "OTP_INVALID_CHALLENGE", 400)
    api.clock.now += timedelta(microseconds=1)
    assert cleanup_auth(api.factory, api.settings, clock=api.clock) == {
        "auth_otp_challenges": 1,
        "auth_rate_limit_buckets": 1,
        "auth_sessions": 1,
    }


def test_cleanup_failure_rolls_back_prior_deletes(account, retention_rows):
    api = account.api

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM auth_rate_limit_buckets"):
            raise SQLAlchemyError("private cleanup diagnostics")

    engine = api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(AuthError, match="SERVICE_UNAVAILABLE"):
            cleanup_auth(api.factory, api.settings, clock=api.clock)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    with api.factory() as db:
        for challenge_id, session_id, _, _ in retention_rows:
            assert db.get(AuthOtpChallenge, challenge_id) is not None
            assert db.get(AuthSession, session_id) is not None
