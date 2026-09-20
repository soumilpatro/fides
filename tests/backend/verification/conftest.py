from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from sqlalchemy import delete, select

from repayments.conftest import api, b6, b7, clock, ctx, engine_env, peers, settings  # noqa: F401
from repayments.conftest import seed as seed_report


@pytest.fixture
def b8(b7):  # noqa: F811
    result = b7.report()
    assert result.status_code == 201
    repayment = result.json()["id"]

    def decide(action="verify", actor="B", identifier=None, key=None, body=None):
        return b7.api.client.post(
            f"/api/v1/repayments/{identifier or repayment}/{action}",
            json={} if body is None else body,
            headers={**b7.headers[actor], "Idempotency-Key": key or uuid4().hex},
        )

    def history(actor="A", identifier=None):
        return b7.api.client.get(
            f"/api/v1/repayments/{identifier or repayment}/verification-history",
            headers=b7.headers[actor],
        )

    try:
        yield SimpleNamespace(
            **vars(b7), repayment=repayment, original=result.json(), decide=decide, history=history
        )
    finally:
        with b7.api.factory.begin() as db:
            ids = (
                select(Repayment.id)
                .join(Commitment)
                .where(Commitment.connection_id == UUID(b7.connection))
            )
            db.execute(
                delete(RepaymentVerification).where(RepaymentVerification.repayment_id.in_(ids))
            )


def seed(b8, amount, status, **values):
    identifier = seed_report(b8, amount, status, **values)
    if status in ("VERIFIED", "DISPUTED"):
        with b8.api.factory.begin() as db:
            row = db.get(Repayment, identifier)
            db.add(
                RepaymentVerification(
                    repayment_id=identifier,
                    decided_by_user_id=b8.users["B"]
                    if row.reported_by_user_id == b8.users["A"]
                    else b8.users["A"],
                    decision=status,
                    decided_at=b8.api.clock.now,
                )
            )
    return identifier
