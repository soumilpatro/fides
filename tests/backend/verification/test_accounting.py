from datetime import timedelta
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.repayments import repayment_accounting
from sqlalchemy import select

from .conftest import seed


@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
@pytest.mark.parametrize(
    "principal,rate,total",
    [(10000, None, 10000), (101, 500, 106), (1, 5000, 2), (10**12, 10000, 2 * 10**12)],
)
def test_interest_currency_and_full_verification(b8, currency, principal, rate, total):
    parent = b8.commitment(
        currency=currency,
        principal_amount_minor=principal,
        terms={"interest_type": "NONE"}
        if rate is None
        else {"interest_type": "SIMPLE_FIXED", "interest_rate_bps": rate},
    )
    repayment = b8.report(parent=parent, currency=currency, amount_minor=total).json()["id"]
    result = b8.decide(identifier=repayment)
    assert result.status_code == 200
    with b8.api.factory() as db:
        assert db.get(Commitment, UUID(parent)).status.value == "FULLY_REPAID"
        event = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.repayment_id == UUID(repayment),
                LedgerEvent.event_type == "REPAYMENT_VERIFIED",
            )
        )
        assert event.event_payload["verified_outstanding"] == 0


@pytest.mark.parametrize("amount,code", [(5000, 200), (5001, 409)])
def test_existing_credit_and_candidate_limit(b8, amount, code):
    seed(b8, 2000, "VERIFIED")
    seed(b8, 3000, "VERIFIED")
    seed(b8, 9000, "DISPUTED")
    seed(b8, 9000, "CANCELLED")
    with b8.api.factory.begin() as db:
        db.get(Repayment, UUID(b8.repayment)).amount_minor = amount
    result = b8.decide()
    assert result.status_code == code
    if code == 409:
        assert result.json()["error"]["code"] == "OVER_REPAYMENT"


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_capacity_effects(b8, action):
    assert b8.decide(action).status_code == 200
    with b8.api.factory.begin() as db:
        _, totals = repayment_accounting(
            db, db.get(Commitment, UUID(b8.identifier)), b8.api.clock.now
        )
        assert totals.pending == 0
        assert totals.verified_outstanding == (9000 if action == "verify" else 10000)
        assert totals.reportable_remaining == totals.verified_outstanding
    assert b8.report(amount_minor=totals.reportable_remaining).status_code == 201


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_pending_overreservation_is_not_decision_capacity(b8, action):
    seed(b8, 15000, "PENDING_VERIFICATION")
    assert b8.decide(action).status_code == 200


def test_verified_over_obligation_fails_safely(b8):
    seed(b8, 10001, "VERIFIED")
    assert b8.decide().status_code == 503


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_current_terms_reduce_obligation(b8, action):
    parent = b8.commitment(
        principal_amount_minor=1000,
        terms={"interest_type": "SIMPLE_FIXED", "interest_rate_bps": 10000},
    )
    repayment = b8.report(parent=parent, amount_minor=2000).json()["id"]
    with b8.api.factory.begin() as db:
        db.add(
            CommitmentTermsVersion(
                commitment_id=UUID(parent),
                version_no=2,
                effective_at=b8.api.clock.now,
                interest_type="NONE",
                grace_period_days=0,
                created_by_user_id=b8.users["A"],
            )
        )
    result = b8.decide(action, identifier=repayment)
    assert result.status_code == (409 if action == "verify" else 200)
    if action == "verify":
        assert result.json()["error"]["code"] == "OVER_REPAYMENT"


def test_highest_current_version_and_event_provenance(b8):
    with b8.api.factory.begin() as db:
        for version, days, rate in [(2, -1, 500), (3, 0, 1000), (4, 1, 9000)]:
            db.add(
                CommitmentTermsVersion(
                    commitment_id=UUID(b8.identifier),
                    version_no=version,
                    effective_at=b8.api.clock.now + timedelta(days=days),
                    interest_type="SIMPLE_FIXED",
                    interest_rate_bps=rate,
                    grace_period_days=365,
                    created_by_user_id=b8.users["B"],
                    schedule_definition={
                        "schedule_mode": "none",
                        "due_timezone": "UTC",
                        "installment_dates": None,
                    },
                )
            )
    assert b8.decide().status_code == 200
    with b8.api.factory() as db:
        ledger = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.repayment_id == UUID(b8.repayment),
                LedgerEvent.event_type == "REPAYMENT_VERIFIED",
            )
        )
        assert db.get(CommitmentTermsVersion, ledger.terms_version_id).version_no == 3
        assert ledger.event_payload["verified_outstanding"] == 10000


def test_dispute_never_requires_terms_calculation(b8):
    with b8.api.factory.begin() as db:
        db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(b8.identifier)
            )
        ).schedule_definition = {"invalid": True}
    assert b8.decide("dispute").status_code == 200
    with b8.api.factory() as db:
        ledger = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.repayment_id == UUID(b8.repayment),
                LedgerEvent.event_type == "REPAYMENT_DISPUTED",
            )
        )
        assert ledger.terms_version_id is None
        assert "verified_outstanding" not in ledger.event_payload


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_no_installment_allocation(b8, action):
    parent = b8.commitment(terms=b8.terms)
    repayment = b8.report(parent=parent, amount_minor=10500).json()["id"]
    with b8.api.factory() as db:
        before = list(
            db.execute(select(CommitmentInstallment.__table__).order_by(CommitmentInstallment.id))
        )
    assert b8.decide(action, identifier=repayment).status_code == 200
    with b8.api.factory() as db:
        assert (
            list(
                db.execute(
                    select(CommitmentInstallment.__table__).order_by(CommitmentInstallment.id)
                )
            )
            == before
        )
