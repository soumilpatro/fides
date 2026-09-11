"""Committed test transactions on the existing migrated fides_test schema.

Unlike the B1 savepoint fixture, these services need independent connections and
real commits. Cleanup targets only UUIDs/HMAC subjects allocated by this test.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.auth.rate_limits import RateLimiter
from app.auth.sessions import SessionService
from app.config import Settings
from app.models.audit_log import AuditLog
from app.models.auth_rate_limit_bucket import AuthRateLimitBucket
from app.models.auth_session import AuthSession
from app.models.user import User
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def clock():
    class Clock:
        now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

        def __call__(self):
            return self.now

    return Clock()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None, app_env="test", otp_provider="fake", auth_rate_limit_hmac_secret=uuid4().hex
    )


@pytest.fixture
def engine_env(db_engine, settings, clock, monkeypatch):
    factory = sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
    users, subjects = [], set()
    original = RateLimiter.subject

    def track(self, domain, value):
        digest = original(self, domain, value)
        subjects.add(digest)
        return digest

    monkeypatch.setattr(RateLimiter, "subject", track)

    def user():
        identifier = uuid4()
        users.append(identifier)
        with factory.begin() as db:
            db.add(User(id=identifier, display_name="Test user", timezone="UTC"))
        return identifier

    service = SessionService(factory, settings, clock=clock)
    try:
        yield SimpleNamespace(
            factory=factory,
            user=user,
            service=service,
            limiter=service.limiter,
            clock=clock,
            settings=settings,
        )
    finally:
        with factory.begin() as db:
            db.execute(delete(AuditLog).where(AuditLog.actor_user_id.in_(users)))
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(users)))
            db.execute(delete(User).where(User.id.in_(users)))
            db.execute(
                delete(AuthRateLimitBucket).where(AuthRateLimitBucket.subject_hash.in_(subjects))
            )
