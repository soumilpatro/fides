from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from sqlalchemy import delete, select

from terms.conftest import api, b6, clock, ctx, engine_env, peers, settings  # noqa: F401


@pytest.fixture
def b7(b6):  # noqa: F811
    def commitment(**values):
        result = b6.request("POST", json={**b6.body, **values})
        assert result.status_code == 201, result.text
        identifier = result.json()["id"]
        assert b6.request("POST", f"/{identifier}/confirm", actor="B").status_code == 200
        return identifier

    identifier = commitment()
    body = {"amount_minor": 1000, "currency": "INR", "payment_date": "2026-09-11", "note": None}

    def report(actor="A", key=None, parent=None, **values):
        return b6.request(
            "POST",
            f"/{parent or identifier}/repayments",
            actor=actor,
            key=key or uuid4().hex,
            json={**body, **values},
        )

    def read(actor="A", repayment=None, parent=None):
        path = (
            "/api/v1/repayments/" + str(repayment)
            if repayment
            else f"/api/v1/commitments/{parent or identifier}/repayments"
        )
        return b6.api.client.get(path, headers=b6.headers[actor])

    try:
        yield SimpleNamespace(
            **vars(b6),
            identifier=identifier,
            report_body=body,
            report=report,
            read=read,
            commitment=commitment,
        )
    finally:
        with b6.api.factory.begin() as db:
            parents = select(Commitment.id).where(Commitment.connection_id == UUID(b6.connection))
            ids = select(Repayment.id).where(Repayment.commitment_id.in_(parents))
            db.execute(delete(AuditLog).where(AuditLog.object_id.in_(ids)))
            db.execute(delete(LedgerEvent).where(LedgerEvent.commitment_id.in_(parents)))
            db.execute(delete(Repayment).where(Repayment.commitment_id.in_(parents)))


def seed(b7, amount, status, **values):
    with b7.api.factory.begin() as db:
        row = Repayment(
            commitment_id=UUID(b7.identifier),
            reported_by_user_id=b7.users["A"],
            amount_minor=amount,
            currency="INR",
            payment_date=b7.api.clock.now.date(),
            reported_at=b7.api.clock.now,
            status=status,
            created_at=b7.api.clock.now,
        )
        for key, value in values.items():
            setattr(row, key, value)
        db.add(row)
        db.flush()
        return row.id
