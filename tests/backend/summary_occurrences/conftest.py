from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.repayment import Repayment
from mutual_closure.conftest import (  # noqa: F401
    api,
    b6,
    b7,
    clock,
    ctx,
    engine_env,
    mc,
    peers,
    settings,
)
from sqlalchemy import insert, select


@pytest.fixture
def occ(mc):  # noqa: F811
    def configure(due="2026-09-11", grace=0, timezone="UTC", status="ACTIVE", parent=None):
        with mc.api.factory.begin() as db:
            p = db.get(Commitment, UUID(parent or mc.identifier))
            p.status = status
            t = db.scalar(
                select(CommitmentTermsVersion)
                .where(CommitmentTermsVersion.commitment_id == p.id)
                .order_by(CommitmentTermsVersion.version_no.desc())
            )
            t.due_date = date.fromisoformat(due) if due else None
            t.grace_period_days = grace
            t.schedule_definition = {
                "schedule_mode": "single" if due else "none",
                "due_timezone": timezone,
                "installment_dates": None,
            }

    def query(kind="upcoming", actor="A", **kwargs):
        return mc.api.client.get("/api/v1/summary/" + kind, headers=mc.headers[actor], **kwargs)

    def bulk(count, due="2026-09-11", zero=False):
        ids = [uuid4() for _ in range(count)]
        with mc.api.factory.begin() as db:
            db.execute(
                insert(Commitment),
                [
                    dict(
                        id=i,
                        connection_id=UUID(mc.connection),
                        borrower_user_id=mc.users["A"],
                        lender_user_id=mc.users["B"],
                        created_by_user_id=mc.users["A"],
                        type="IOU",
                        status="ACTIVE",
                        principal_amount_minor=10000,
                        currency="INR",
                    )
                    for i in ids
                ],
            )
            db.execute(
                insert(CommitmentTermsVersion),
                [
                    dict(
                        commitment_id=i,
                        version_no=1,
                        effective_at=mc.api.clock.now,
                        interest_type="NONE",
                        grace_period_days=0,
                        created_by_user_id=mc.users["A"],
                        due_date=date.fromisoformat(due),
                        schedule_definition={
                            "schedule_mode": "single",
                            "due_timezone": "UTC",
                            "installment_dates": None,
                        },
                    )
                    for i in ids
                ],
            )
            if zero:
                db.execute(
                    insert(Repayment),
                    [
                        dict(
                            commitment_id=i,
                            reported_by_user_id=mc.users["A"],
                            amount_minor=10000,
                            currency="INR",
                            payment_date=mc.api.clock.now.date(),
                            reported_at=mc.api.clock.now,
                            status="VERIFIED",
                        )
                        for i in ids
                    ],
                )
        return ids

    configure()
    return SimpleNamespace(**vars(mc), configure=configure, query=query, bulk=bulk)


def items(response):
    assert response.status_code == 200, response.text
    return response.json()["items"]


def unavailable(response):
    assert response.status_code == 503, response.text
    assert response.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "Service is temporarily unavailable.",
        }
    }
