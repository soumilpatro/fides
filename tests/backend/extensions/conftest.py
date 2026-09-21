from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.models.audit_log import AuditLog
from app.models.extension_request import ExtensionRequest
from sqlalchemy import delete, select

from verification.conftest import (  # noqa: F401
    api,
    b6,
    b7,
    b8,
    clock,
    ctx,
    engine_env,
    peers,
    settings,
)


@pytest.fixture
def b10(b8):  # noqa: F811
    identifier = b8.commitment(
        terms={
            "due_date": "2026-10-10",
            "interest_type": "SIMPLE_FIXED",
            "interest_rate_bps": 500,
            "grace_period_days": 3,
        }
    )

    def create(actor="A", parent=None, key=None, **values):
        return b8.api.client.post(
            f"/api/v1/commitments/{parent or identifier}/extension-requests",
            json={"requested_due_date": "2026-11-10", **values},
            headers={**b8.headers[actor], "Idempotency-Key": key or uuid4().hex},
        )

    def decide(extension, action="accept", actor="B", key=None):
        return b8.api.client.post(
            f"/api/v1/extension-requests/{extension}/{action}",
            json={},
            headers={**b8.headers[actor], "Idempotency-Key": key or uuid4().hex},
        )

    def read(actor="A", parent=None):
        return b8.api.client.get(
            f"/api/v1/commitments/{parent or identifier}/extension-requests",
            headers=b8.headers[actor],
        )

    def timeline(actor="A"):
        return b8.api.client.get(
            f"/api/v1/commitments/{identifier}/ledger", headers=b8.headers[actor]
        )

    try:
        yield SimpleNamespace(
            **{
                **vars(b8),
                "identifier": identifier,
                "financial": b8,
                "create": create,
                "decide": decide,
                "read": read,
                "timeline": timeline,
            }
        )
    finally:
        with b8.api.factory.begin() as db:
            ids = list(
                db.scalars(
                    select(ExtensionRequest.id).where(
                        ExtensionRequest.requested_by_user_id.in_(b8.users.values())
                    )
                )
            )
            db.execute(delete(AuditLog).where(AuditLog.object_id.in_(ids)))
            db.execute(delete(ExtensionRequest).where(ExtensionRequest.id.in_(ids)))


def requested(env, **kwargs):
    response = env.create(**kwargs)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def parent_id(env):
    return UUID(env.identifier)
