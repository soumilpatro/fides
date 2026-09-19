from datetime import timedelta
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.repayments import reporting_capacity
from sqlalchemy import select

from .conftest import seed


@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
@pytest.mark.parametrize(
    "principal,rate,obligation",
    [
        (10000, None, 10000),
        (101, 500, 106),
        (1, 5000, 2),
        (1_000_000_000_000, 10000, 2_000_000_000_000),
    ],
)
def test_obligation_currency_and_rounding(b7, currency, principal, rate, obligation):
    terms = (
        {"interest_type": "NONE"}
        if rate is None
        else {"interest_type": "SIMPLE_FIXED", "interest_rate_bps": rate}
    )
    parent = b7.commitment(currency=currency, principal_amount_minor=principal, terms=terms)
    result = b7.report(parent=parent, currency=currency, amount_minor=obligation)
    assert result.status_code == 201, result.text
    assert (
        b7.report(parent=parent, currency=currency, amount_minor=1).json()["error"]["code"]
        == "OVER_REPAYMENT"
    )


@pytest.mark.parametrize("status", ["VERIFIED", "PENDING_VERIFICATION", "DISPUTED", "CANCELLED"])
def test_distinct_verified_and_pending_totals(b7, status):
    seed(b7, 2000, status)
    seed(b7, 1000, status)
    with b7.api.factory.begin() as db:
        parent = db.scalar(
            select(Commitment).where(Commitment.id == UUID(b7.identifier)).with_for_update()
        )
        _, capacity = reporting_capacity(db, parent, b7.api.clock.now)
    assert capacity.obligation == 10000
    assert capacity.verified_outstanding == (7000 if status == "VERIFIED" else 10000)
    assert capacity.pending == (3000 if status == "PENDING_VERIFICATION" else 0)
    assert capacity.reportable_remaining == (
        7000 if status in ("VERIFIED", "PENDING_VERIFICATION") else 10000
    )


@pytest.mark.parametrize("amount,success", [(4999, True), (5000, True), (5001, False)])
def test_combined_reservation(b7, amount, success):
    seed(b7, 2000, "VERIFIED")
    seed(b7, 3000, "PENDING_VERIFICATION")
    seed(b7, 9000, "DISPUTED")
    result = b7.report(amount_minor=amount)
    assert result.status_code == (201 if success else 409)
    if not success:
        assert result.json()["error"]["code"] == "OVER_REPAYMENT"


def test_multiple_reports_reserve_until_full(b7):
    for amount in (3000, 3000, 4000):
        assert b7.report(amount_minor=amount).status_code == 201
    assert b7.report(amount_minor=1).json()["error"]["code"] == "OVER_REPAYMENT"
    with b7.api.factory.begin() as db:
        _, capacity = reporting_capacity(
            db, db.get(Commitment, UUID(b7.identifier)), b7.api.clock.now
        )
        assert capacity.verified_outstanding == 10000
        assert capacity.reportable_remaining == 0


@pytest.mark.parametrize(
    "kind",
    [
        "verified_over",
        "pending_over",
        "wrong_currency",
        "wrong_reporter",
        "missing_terms",
        "invalid_terms",
    ],
)
def test_corruption_fails_safely(b7, kind):
    if kind == "verified_over":
        seed(b7, 10001, "VERIFIED")
    elif kind == "pending_over":
        seed(b7, 10001, "PENDING_VERIFICATION")
    elif kind == "wrong_currency":
        seed(b7, 1, "VERIFIED", currency="USD")
    elif kind == "wrong_reporter":
        seed(b7, 1, "VERIFIED", reported_by_user_id=b7.users["C"])
    else:
        with b7.api.factory.begin() as db:
            terms = db.scalar(
                select(CommitmentTermsVersion).where(
                    CommitmentTermsVersion.commitment_id == UUID(b7.identifier)
                )
            )
            if kind == "missing_terms":
                terms.effective_at = b7.api.clock.now + timedelta(days=1)
            else:
                terms.schedule_definition = {"unexpected": "secret"}
    result = b7.report()
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_highest_effective_version_not_latest_timestamp(b7):
    with b7.api.factory.begin() as db:
        base = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(b7.identifier)
            )
        )
        base.effective_at = b7.api.clock.now - timedelta(days=1)
        for version, days, rate in [(2, -3, 500), (3, -2, 1000), (4, 1, 9000)]:
            db.add(
                CommitmentTermsVersion(
                    commitment_id=base.commitment_id,
                    version_no=version,
                    effective_at=b7.api.clock.now + timedelta(days=days),
                    interest_type="SIMPLE_FIXED",
                    interest_rate_bps=rate,
                    grace_period_days=0,
                    created_by_user_id=b7.users["A"],
                    schedule_definition={
                        "schedule_mode": "none",
                        "due_timezone": "UTC",
                        "installment_dates": None,
                    },
                )
            )
    response = b7.report(amount_minor=11000)
    assert response.status_code == 201
    assert b7.report(amount_minor=1).status_code == 409
