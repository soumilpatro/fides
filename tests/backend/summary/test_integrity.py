from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, update

from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.ledger_event import LedgerEvent
from repayments.conftest import seed
from .conftest import read, unavailable


@pytest.mark.parametrize(
    "kind",
    [
        "missing_terms",
        "future_only",
        "currency",
        "principal",
        "repayment_currency",
        "reporter",
        "overpaid",
        "terms_creator",
        "terms_metadata",
        "rate",
        "mode",
    ],
)
def test_corrupt_authoritative_inputs(b7, kind):
    with b7.api.factory.begin() as db:
        parent = db.get(Commitment, UUID(b7.identifier))
        terms = db.scalar(
            select(CommitmentTermsVersion).where(CommitmentTermsVersion.commitment_id == parent.id)
        )
        if kind == "missing_terms":
            # Remove the optional historical FK before constructing missing-authority corruption.
            db.execute(
                update(LedgerEvent)
                .where(LedgerEvent.terms_version_id == terms.id)
                .values(terms_version_id=None)
            )
            db.delete(terms)
        if kind == "future_only":
            terms.effective_at = b7.api.clock.now + timedelta(days=1)
        if kind == "currency":
            parent.currency = "EUR"
        if kind == "principal":
            parent.principal_amount_minor = 1_000_000_000_001
        if kind == "terms_creator":
            terms.created_by_user_id = b7.users["C"]
        if kind == "terms_metadata":
            terms.schedule_definition = {"private": "must not leak"}
        if kind == "rate":
            terms.interest_rate_bps = 1
        if kind == "mode":
            terms.schedule_definition = {
                "schedule_mode": "single",
                "due_timezone": "UTC",
                "installment_dates": None,
            }
    if kind == "repayment_currency":
        seed(b7, 100, "DISPUTED", currency="USD")
    if kind == "reporter":
        seed(b7, 100, "CANCELLED", reported_by_user_id=b7.users["C"])
    if kind == "overpaid":
        seed(b7, 10001, "VERIFIED")
    unavailable(read(b7))


def test_no_partial_summary(b7):
    b7.commitment(currency="USD")
    seed(b7, 10001, "VERIFIED")
    unavailable(read(b7))


def test_unrelated_corruption_does_not_fail_actor(b7):
    with b7.api.factory.begin() as db:
        db.get(Commitment, UUID(b7.identifier)).status = "CLOSED"
    assert read(b7, "C").status_code == 200


@pytest.mark.parametrize("excess", [0, 1])
@pytest.mark.parametrize("role", ["borrower", "lender"])
def test_real_aggregate_safe_integer_boundary(ctx, excess, role):
    from uuid import uuid4
    from sqlalchemy import insert
    from app.api.summary_schemas import MAX_SAFE_INTEGER

    # Real persisted obligations, each within the approved individual principal cap.
    # No mocking of accounting: thousands of independent records cross the JSON boundary.
    remaining = MAX_SAFE_INTEGER + excess
    parents, versions = [], []
    while remaining:
        principal = min(remaining, 1_000_000_000_000)
        remaining -= principal
        identifier = uuid4()
        parents.append(
            dict(
                id=identifier,
                connection_id=UUID(ctx.connection),
                borrower_user_id=ctx.users["A" if role == "borrower" else "B"],
                lender_user_id=ctx.users["B" if role == "borrower" else "A"],
                created_by_user_id=ctx.users["A"],
                type="IOU",
                status="ACTIVE",
                principal_amount_minor=principal,
                currency="INR",
            )
        )
        versions.append(
            dict(
                commitment_id=identifier,
                version_no=1,
                effective_at=ctx.api.clock.now,
                interest_type="NONE",
                grace_period_days=0,
                created_by_user_id=ctx.users["A"],
            )
        )
    with ctx.api.factory.begin() as db:
        db.execute(insert(Commitment), parents)
        db.execute(insert(CommitmentTermsVersion), versions)
    result = read(ctx)
    if excess:
        unavailable(result)
    else:
        assert result.status_code == 200, result.text
        row = result.json()["currencies"][0]
        assert (
            row["borrowed_outstanding_minor" if role == "borrower" else "lent_outstanding_minor"]
            == MAX_SAFE_INTEGER
        )
        assert row["net_position_minor"] == MAX_SAFE_INTEGER * (-1 if role == "borrower" else 1)
