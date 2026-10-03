from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.extension_request import ExtensionRequest
from app.models.mutual_closure_request import MutualClosureRequest
from app.models.notification_preference import NotificationPreference
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from sqlalchemy import delete, select

from repayments.conftest import (  # noqa: F401
    api,
    b6,
    b7,
    clock,
    ctx,
    engine_env,
    peers,
    settings,
)


@pytest.fixture
def mc(b7):  # noqa: F811
    def create(actor="A", parent=None, key=None, **values):
        return b7.api.client.post(
            f"/api/v1/commitments/{parent or b7.identifier}/closure-requests",
            json=values,
            headers={**b7.headers[actor], "Idempotency-Key": key or uuid4().hex},
        )

    def decide(identifier, action="accept", actor="B", key=None):
        return b7.api.client.post(
            f"/api/v1/closure-requests/{identifier}/{action}",
            json={},
            headers={**b7.headers[actor], "Idempotency-Key": key or uuid4().hex},
        )

    def read(actor="A", identifier=None, parent=None):
        path = (
            f"/api/v1/closure-requests/{identifier}"
            if identifier
            else f"/api/v1/commitments/{parent or b7.identifier}/closure-requests"
        )
        return b7.api.client.get(path, headers=b7.headers[actor])

    def verify(identifier, action="verify", actor="B", key=None):
        return b7.api.client.post(
            f"/api/v1/repayments/{identifier}/{action}",
            json={},
            headers={**b7.headers[actor], "Idempotency-Key": key or uuid4().hex},
        )

    def extension(identifier=None, action="accept", actor=None, key=None):
        path = (
            f"/api/v1/extension-requests/{identifier}/{action}"
            if identifier
            else f"/api/v1/commitments/{b7.identifier}/extension-requests"
        )
        return b7.api.client.post(
            path,
            json={} if identifier else {"requested_due_date": "2026-12-10"},
            headers={
                **b7.headers[actor or ("B" if identifier else "A")],
                "Idempotency-Key": key or uuid4().hex,
            },
        )

    def timeline():
        return b7.api.client.get(
            f"/api/v1/commitments/{b7.identifier}/ledger", headers=b7.headers["A"]
        )

    try:
        yield SimpleNamespace(
            **vars(b7),
            create=create,
            decide=decide,
            closure_read=read,
            verify=verify,
            extension=extension,
            timeline=timeline,
        )
    finally:
        with b7.api.factory.begin() as db:
            parents = select(Commitment.id).where(Commitment.connection_id == UUID(b7.connection))
            ids = select(MutualClosureRequest.id).where(
                MutualClosureRequest.commitment_id.in_(parents)
            )
            db.execute(delete(AuditLog).where(AuditLog.object_id.in_(ids)))
            db.execute(
                delete(MutualClosureRequest).where(MutualClosureRequest.commitment_id.in_(parents))
            )
            db.execute(
                delete(AuditLog).where(
                    AuditLog.object_id.in_(
                        select(ExtensionRequest.id).where(
                            ExtensionRequest.commitment_id.in_(parents)
                        )
                    )
                )
            )
            db.execute(delete(ExtensionRequest).where(ExtensionRequest.commitment_id.in_(parents)))
            db.execute(
                delete(RepaymentVerification).where(
                    RepaymentVerification.repayment_id.in_(
                        select(Repayment.id).where(Repayment.commitment_id.in_(parents))
                    )
                )
            )
            db.execute(
                delete(NotificationPreference).where(
                    NotificationPreference.user_id.in_(b7.users.values())
                )
            )


def requested(mc, **values):
    result = mc.create(**values)
    assert result.status_code == 201, result.text
    return result.json()["id"]


def error(response, code, status=409):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
