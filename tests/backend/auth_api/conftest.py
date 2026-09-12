from types import SimpleNamespace

import pytest
from app.api.auth import get_auth_service, get_client_ip
from app.auth.challenges import ChallengeService
from app.auth.providers import FakeOtpProvider
from app.main import create_app
from app.models.audit_log import AuditLog
from app.models.auth_identity import AuthIdentity
from app.models.auth_otp_challenge import AuthOtpChallenge
from app.models.auth_session import AuthSession
from app.models.user import User
from auth_engine.conftest import clock, engine_env, settings  # noqa: F401
from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select

PHONE = "+14155552671"


@pytest.fixture
def api(engine_env):  # noqa: F811 - imported pytest fixture is injected by name
    env = engine_env
    provider = FakeOtpProvider(clock=env.clock)
    service = ChallengeService(env.factory, env.settings, provider, clock=env.clock)
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_client_ip] = lambda: "192.0.2.1"
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield SimpleNamespace(
                **vars(env), client=client, provider=provider, challenges=service, app=app
            )
    finally:
        with env.factory.begin() as db:
            users = list(db.scalars(select(User.id).where(User.phone_e164 == PHONE)))
            challenges = list(
                db.scalars(select(AuthOtpChallenge.id).where(AuthOtpChallenge.phone_e164 == PHONE))
            )
            db.execute(
                delete(AuditLog).where(
                    or_(AuditLog.actor_user_id.in_(users), AuditLog.object_id.in_(challenges))
                )
            )
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(users)))
            db.execute(
                delete(AuthIdentity).where(
                    or_(
                        AuthIdentity.user_id.in_(users),
                        (AuthIdentity.provider == "phone")
                        & (AuthIdentity.provider_subject == PHONE),
                    )
                )
            )
            db.execute(delete(User).where(User.id.in_(users)))
            db.execute(delete(AuthOtpChallenge).where(AuthOtpChallenge.id.in_(challenges)))
