from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.api.auth import get_auth_service, get_client_ip
from app.api.auth_schemas import MeResponse, OtpRequestResponse
from app.api.commitment_schemas import CommitmentRequest
from app.api.me import get_account_service
from app.api.repayment_schemas import RepaymentRequest
from app.core.errors import AuthError, ResourceUnavailable
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def security_app():
    app = create_app()
    calls = []

    async def request(body, **kwargs):
        calls.append(body)
        return OtpRequestResponse(
            challenge_id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            resend_after_seconds=60,
            message="Verification requested.",
        )

    def resolve(header):
        if header != "Bearer audit-test-only":
            raise AuthError("AUTH_REQUIRED")
        return object()

    def account(principal):
        now = datetime.now(UTC)
        return MeResponse(
            id=uuid4(),
            phone_e164=None,
            display_name="Audit fixture",
            timezone="UTC",
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )

    service = SimpleNamespace(request=request, session_service=SimpleNamespace(resolve=resolve))
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_client_ip] = lambda: "192.0.2.1"
    app.dependency_overrides[get_account_service] = lambda: SimpleNamespace(get=account)

    @app.post("/api/v1/commitments/security-test/amount")
    def commitment_amount(body: CommitmentRequest):
        return {}

    @app.post("/api/v1/commitments/security-test/amount/repayments")
    def repayment_amount(body: RepaymentRequest):
        return {}

    @app.get("/api/v1/auth/security-test/unavailable")
    def unavailable():
        raise ResourceUnavailable()

    @app.get("/api/v1/auth/security-test/rate-limit")
    def rate_limit():
        raise AuthError("OTP_RATE_LIMITED", retry_after_seconds=60)

    @app.get("/api/v1/auth/security-test/failure")
    def failure():
        raise RuntimeError("B14-SYNTHETIC-SECRET-SENTINEL")

    return SimpleNamespace(app=app, calls=calls)


@pytest.fixture
def security_client(security_app):
    # Explicit substitutes keep these HTTP tests independent of DB/providers.
    with TestClient(security_app.app, raise_server_exceptions=False) as client:
        yield client
