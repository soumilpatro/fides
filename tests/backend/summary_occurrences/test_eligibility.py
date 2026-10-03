from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.user import User
from app.reminders import candidates, snapshot_query
from repayments.conftest import seed
from sqlalchemy import select

from .conftest import items


@pytest.mark.parametrize("offset,expected", [(-1, 0), (0, 1), (1, 1), (7, 1), (8, 0)])
def test_upcoming_boundaries(occ, offset, expected):
    occ.configure(due=(date(2026, 9, 11) + timedelta(days=offset)).isoformat(), grace=10)
    assert len(items(occ.query())) == expected


@pytest.mark.parametrize("grace", [0, 1, 7, 365])
@pytest.mark.parametrize("after", [-1, 0, 1, 5])
def test_overdue_start(occ, grace, after):
    occ.configure(due=(date(2026, 9, 11) - timedelta(days=grace + after)).isoformat(), grace=grace)
    assert len(items(occ.query("overdue"))) == int(after >= 1)


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize(
    "status",
    [
        "ACTIVE",
        "PARTIALLY_REPAID",
        "PENDING_CONFIRMATION",
        "REJECTED",
        "CANCELLED",
        "FULLY_REPAID",
        "CLOSED",
        "DEFAULTED",
        "DRAFT",
        "CONFIRMED",
        "DISPUTED",
    ],
)
def test_states(occ, kind, status):
    occ.configure(due="2026-09-10" if kind == "overdue" else "2026-09-11", status=status)
    assert len(items(occ.query(kind))) == int(status in {"ACTIVE", "PARTIALLY_REPAID"})


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize("legacy", [True, False])
def test_no_deadline(occ, kind, legacy):
    occ.configure(due=None)
    if legacy:
        with occ.api.factory.begin() as db:
            t = db.scalar(
                select(CommitmentTermsVersion).where(
                    CommitmentTermsVersion.commitment_id == UUID(occ.identifier)
                )
            )
            t.schedule_definition = None
    assert items(occ.query(kind)) == []


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize(
    "status,amount,expected",
    [
        ("VERIFIED", 1000, 9000),
        ("VERIFIED", 10000, 0),
        ("PENDING_VERIFICATION", 1000, 10000),
        ("DISPUTED", 1000, 10000),
        ("CANCELLED", 1000, 10000),
    ],
)
def test_accounting(occ, kind, status, amount, expected):
    occ.configure(due="2026-09-10" if kind == "overdue" else "2026-09-11")
    seed(occ, amount, status)
    result = items(occ.query(kind))
    assert len(result) == int(expected > 0)
    if result:
        assert result[0]["verified_outstanding_minor"] == expected


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize("actor,role,other", [("A", "BORROWER", "B"), ("B", "LENDER", "A")])
def test_roles(occ, kind, actor, role, other):
    occ.configure(due="2026-09-10" if kind == "overdue" else "2026-09-11")
    row = items(occ.query(kind, actor))[0]
    assert row["role"] == role
    assert row["counterparty"] == {
        "id": str(occ.users[other]),
        "display_name": "Test user",
    }
    assert items(occ.query(kind, "C")) == []


@pytest.mark.parametrize(
    "timezone,expected", [("Pacific/Kiritimati", True), ("America/Los_Angeles", False)]
)
@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
def test_contract_timezone(occ, timezone, expected, kind):
    occ.api.clock.now = datetime(2026, 9, 11, 0, 30, tzinfo=UTC)
    occ.configure(due="2026-09-18" if kind == "upcoming" else "2026-09-10", timezone=timezone)
    with occ.api.factory.begin() as db:
        db.get(User, occ.users["A"]).timezone = "Europe/London"
        term = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(occ.identifier)
            )
        )
        term.effective_at = occ.api.clock.now - timedelta(days=1)
    assert bool(items(occ.query(kind))) == expected


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
def test_extension_and_history(occ, kind):
    occ.configure(due="2026-09-10" if kind == "overdue" else "2026-09-11")
    extension = occ.extension().json()["id"]
    assert occ.extension(extension).status_code == 200
    assert items(occ.query(kind)) == []
    assert occ.timeline().status_code == 200


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
def test_reminder_agreement(occ, kind):
    occ.configure(due="2026-09-10" if kind == "overdue" else "2026-09-14")
    with occ.api.factory() as db:
        row = db.execute(snapshot_query([UUID(occ.identifier)], occ.api.clock.now)).one()
        planned = candidates(row, occ.api.clock.now)
    assert planned and items(occ.query(kind))


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
def test_existing_fixed_interest_accounting(occ, kind, currency):
    occ.configure(due="2026-09-10" if kind == "overdue" else "2026-09-11")
    with occ.api.factory.begin() as db:
        parent = db.get(Commitment, UUID(occ.identifier))
        parent.currency = currency
        term = db.scalar(
            select(CommitmentTermsVersion).where(CommitmentTermsVersion.commitment_id == parent.id)
        )
        term.interest_type = "SIMPLE_FIXED"
        term.interest_rate_bps = 500
    seed(occ, 1000, "VERIFIED", currency=currency)
    row = items(occ.query(kind))[0]
    assert row["verified_outstanding_minor"] == 9500 and row["currency"] == currency
