from datetime import date
from uuid import UUID

import pytest
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from sqlalchemy import select

from .conftest import items, unavailable


@pytest.fixture
def schedule(occ):
    occ.configure(due=None)
    identifier = occ.commitment(
        terms={
            "interest_type": "NONE",
            "installment_dates": [
                "2026-09-10",
                "2026-09-11",
                "2026-09-18",
                "2026-09-19",
            ],
        }
    )
    with occ.api.factory() as db:
        rows = list(
            db.scalars(
                select(CommitmentInstallment)
                .where(CommitmentInstallment.commitment_id == UUID(identifier))
                .order_by(CommitmentInstallment.sequence_no)
            )
        )
    return occ, identifier, rows


@pytest.mark.parametrize("kind,indices", [("upcoming", [1, 2]), ("overdue", [0])])
@pytest.mark.parametrize("status", ["PENDING", "PARTIALLY_PAID", "PAID", "OVERDUE", "CANCELLED"])
def test_informational_occurrences(schedule, kind, indices, status):
    occ, identifier, rows = schedule
    with occ.api.factory.begin() as db:
        for row in rows:
            db.get(CommitmentInstallment, row.id).status = status
    result = items(occ.query(kind))
    assert [r["installment_id"] for r in result] == [str(rows[i].id) for i in indices]
    assert all(
        r["commitment_id"] == identifier
        and r["schedule_mode"] == "installments"
        and r["verified_outstanding_minor"] == 10000
        for r in result
    )
    assert all(
        not {
            "total_due_minor",
            "principal_amount_minor",
            "interest_amount_minor",
            "unpaid_amount_minor",
        }
        & set(r)
        for r in result
    )


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "sequence",
        "date",
        "parent",
        "principal",
        "interest",
        "total",
        "excess",
    ],
)
def test_schedule_integrity(schedule, kind, corruption):
    occ, identifier, rows = schedule
    with occ.api.factory.begin() as db:
        row = db.get(CommitmentInstallment, rows[0].id)
        if corruption == "missing":
            db.delete(row)
        elif corruption == "sequence":
            row.sequence_no = 9
        elif corruption == "date":
            row.due_date = date(2026, 9, 9)
        elif corruption == "parent":
            row.commitment_id = UUID(occ.identifier)
        elif corruption == "principal":
            row.principal_amount_minor += 1
        elif corruption == "interest":
            row.interest_amount_minor += 1
        elif corruption == "total":
            row.total_due_minor += 1
        else:
            for seq in range(5, 67):
                db.add(
                    CommitmentInstallment(
                        commitment_id=UUID(identifier),
                        terms_version_id=row.terms_version_id,
                        sequence_no=seq,
                        due_date=date(2026, 12, 1),
                        principal_amount_minor=1,
                        interest_amount_minor=0,
                        total_due_minor=1,
                        status="PENDING",
                    )
                )
    unavailable(occ.query(kind))


@pytest.mark.parametrize("due", [None, "2026-09-11"])
def test_none_single_children_invalid(occ, due):
    occ.configure(due=due)
    with occ.api.factory.begin() as db:
        t = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(occ.identifier)
            )
        )
        db.add(
            CommitmentInstallment(
                commitment_id=t.commitment_id,
                terms_version_id=t.id,
                sequence_no=1,
                due_date=date(2026, 9, 11),
                principal_amount_minor=10000,
                interest_amount_minor=0,
                total_due_minor=10000,
                status="PENDING",
            )
        )
    unavailable(occ.query())


def test_only_current_version(schedule):
    occ, identifier, rows = schedule
    with occ.api.factory.begin() as db:
        old = db.get(CommitmentTermsVersion, rows[0].terms_version_id)
        db.add(
            CommitmentTermsVersion(
                commitment_id=old.commitment_id,
                version_no=2,
                effective_at=occ.api.clock.now,
                due_date=date(2026, 9, 13),
                interest_type="NONE",
                grace_period_days=0,
                schedule_definition={
                    "schedule_mode": "single",
                    "due_timezone": "UTC",
                    "installment_dates": None,
                },
                created_by_user_id=occ.users["B"],
            )
        )
    result = items(occ.query())
    assert (
        len(result) == 1
        and result[0]["installment_id"] is None
        and result[0]["due_date"] == "2026-09-13"
    )
