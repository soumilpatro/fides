from datetime import timedelta
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.enums import CommitmentStatus
from sqlalchemy import select

from repayments.conftest import seed

from .conftest import bucket, read, unavailable


@pytest.mark.parametrize("actor,borrowed,lent", [("A", 10000, 0), ("B", 0, 10000), ("C", 0, 0)])
def test_perspectives(b7, actor, borrowed, lent):
    assert bucket(b7, actor) == {
        "currency": "INR",
        "borrowed_outstanding_minor": borrowed,
        "lent_outstanding_minor": lent,
        "net_position_minor": lent - borrowed,
    }


@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
@pytest.mark.parametrize("role", ["BORROWER", "LENDER"])
def test_multiple_independent_commitments(b7, currency, role):
    b7.commitment(currency=currency, actor_role=role, principal_amount_minor=321)
    b7.commitment(currency=currency, actor_role=role, principal_amount_minor=123)
    result = read(b7).json()["currencies"]
    for row in result:
        borrowed = 10000 if row["currency"] == "INR" else 0
        lent = 0
        if row["currency"] == currency:
            if role == "BORROWER":
                borrowed += 444
            else:
                lent += 444
        assert row == {
            "currency": row["currency"],
            "borrowed_outstanding_minor": borrowed,
            "lent_outstanding_minor": lent,
            "net_position_minor": lent - borrowed,
        }


@pytest.mark.parametrize(
    "rate,principal,interest",
    [
        (None, 10001, 0),
        (1, 5000, 1),
        (1, 4999, 0),
        (500, 10001, 500),
        (10000, 10001, 10001),
    ],
)
def test_shared_interest_rounding(b7, rate, principal, interest):
    b7.commitment(
        currency="USD",
        principal_amount_minor=principal,
        terms={
            "interest_type": "NONE" if rate is None else "SIMPLE_FIXED",
            "interest_rate_bps": rate,
        },
    )
    assert bucket(b7, currency="USD")["borrowed_outstanding_minor"] == principal + interest


@pytest.mark.parametrize("status", ["PENDING_VERIFICATION", "VERIFIED", "DISPUTED", "CANCELLED"])
def test_repayment_statuses(b7, status):
    seed(b7, 1234, status)
    assert bucket(b7)["borrowed_outstanding_minor"] == (8766 if status == "VERIFIED" else 10000)


@pytest.mark.parametrize("status", list(CommitmentStatus))
def test_state_matrix(b7, status):
    with b7.api.factory.begin() as db:
        db.get(Commitment, UUID(b7.identifier)).status = status
    if status == CommitmentStatus.FULLY_REPAID:
        seed(b7, 10000, "VERIFIED")
    if status.value in ("DRAFT", "CONFIRMED", "DISPUTED", "DEFAULTED"):
        unavailable(read(b7))
    else:
        expected = 10000 if status.value in ("ACTIVE", "PARTIALLY_REPAID") else 0
        assert bucket(b7)["borrowed_outstanding_minor"] == expected


@pytest.mark.parametrize("verified", [0, 9999, 10001])
def test_inconsistent_fully_repaid(b7, verified):
    with b7.api.factory.begin() as db:
        db.get(Commitment, UUID(b7.identifier)).status = "FULLY_REPAID"
    if verified:
        seed(b7, verified, "VERIFIED")
    unavailable(read(b7))


def test_partial_pending_disputed_do_not_mask_outstanding(b7):
    seed(b7, 1234, "VERIFIED")
    seed(b7, 8766, "PENDING_VERIFICATION")
    seed(b7, 10000, "DISPUTED")
    with b7.api.factory.begin() as db:
        db.get(Commitment, UUID(b7.identifier)).status = "PARTIALLY_REPAID"
    assert bucket(b7)["borrowed_outstanding_minor"] == 8766


@pytest.mark.parametrize(
    "schedule",
    [
        None,
        {},
        {"due_date": "2020-01-01"},
        {"due_date": "2026-09-11", "grace_period_days": 365},
        {"due_date": "2099-01-01"},
        {"installment_dates": ["2020-01-01", "2099-01-01"]},
    ],
)
def test_schedules_do_not_change_whole_obligation(b7, schedule):
    values = {} if schedule is None else {"terms": {"interest_type": "NONE", **schedule}}
    identifier = b7.commitment(currency="GBP", **values)
    seed(b7, 1111, "VERIFIED", commitment_id=UUID(identifier), currency="GBP")
    assert bucket(b7, currency="GBP")["borrowed_outstanding_minor"] == 8889


def test_highest_effective_version_not_creation_time(b7):
    with b7.api.factory.begin() as db:
        first = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(b7.identifier)
            )
        )
        for version, rate, delta in [(2, 1000, 0), (3, 2000, 1)]:
            db.add(
                CommitmentTermsVersion(
                    commitment_id=first.commitment_id,
                    version_no=version,
                    effective_at=b7.api.clock.now + timedelta(days=delta),
                    interest_type="SIMPLE_FIXED",
                    interest_rate_bps=rate,
                    grace_period_days=0,
                    created_by_user_id=b7.users["A"],
                    created_at=b7.api.clock.now - timedelta(days=version),
                    schedule_definition={
                        "schedule_mode": "none",
                        "due_timezone": "UTC",
                        "installment_dates": None,
                    },
                )
            )
    assert bucket(b7)["borrowed_outstanding_minor"] == 11000


@pytest.mark.parametrize("action", [None, "accept", "reject"])
def test_extensions(b10, action):
    before = read(b10).json()
    result = b10.create()
    assert result.status_code == 201
    if action:
        assert b10.decide(result.json()["id"], action).status_code == 200
    assert read(b10).json() == before


@pytest.mark.parametrize("amount", [9999, 10000, 10001])
def test_net_positive_zero_negative(b7, amount):
    b7.commitment(actor_role="LENDER", principal_amount_minor=amount)
    assert bucket(b7)["net_position_minor"] == amount - 10000
