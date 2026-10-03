from datetime import date, timedelta
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from repayments.conftest import seed
from sqlalchemy import delete, select, update

from .conftest import items, unavailable


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "future",
        "timezone",
        "dated_null",
        "mode",
        "dates",
        "interest",
        "principal",
        "repayment_currency",
        "reporter",
        "overpayment",
        "terms_creator",
        "overflow",
    ],
)
def test_corruption_fails_even_when_filtered(occ, kind, corruption):
    # Far-future schedules must still be validated before eligibility filtering.
    occ.configure(due="2026-12-10")
    if corruption in {"repayment_currency", "reporter", "overpayment"}:
        seed(occ, 10001 if corruption == "overpayment" else 1000, "VERIFIED")
    with occ.api.factory.begin() as db:
        parent = db.get(Commitment, UUID(occ.identifier))
        term = db.scalar(
            select(CommitmentTermsVersion).where(CommitmentTermsVersion.commitment_id == parent.id)
        )
        if corruption == "missing":
            db.execute(
                update(LedgerEvent)
                .where(LedgerEvent.terms_version_id == term.id)
                .values(terms_version_id=None)
            )
            db.execute(delete(CommitmentTermsVersion).where(CommitmentTermsVersion.id == term.id))
        if corruption == "future":
            term.effective_at = occ.api.clock.now + timedelta(seconds=1)
        if corruption == "timezone":
            term.schedule_definition = {
                **term.schedule_definition,
                "due_timezone": "Invalid/Zone",
            }
        if corruption == "dated_null":
            term.schedule_definition = None
        if corruption == "mode":
            term.schedule_definition = {
                **term.schedule_definition,
                "schedule_mode": "none",
            }
        if corruption == "dates":
            term.schedule_definition = {
                **term.schedule_definition,
                "installment_dates": ["bad"],
            }
        if corruption == "interest":
            term.interest_type = "SIMPLE_FIXED"
            term.interest_rate_bps = None
        if corruption == "principal":
            parent.principal_amount_minor = 1_000_000_000_001
        if corruption == "terms_creator":
            term.created_by_user_id = occ.users["C"]
        if corruption == "overflow":
            term.due_date = date.max
        if corruption in {"repayment_currency", "reporter"}:
            repayment = db.scalar(select(Repayment).where(Repayment.commitment_id == parent.id))
            if corruption == "repayment_currency":
                repayment.currency = "USD"
            else:
                repayment.reported_by_user_id = occ.users["C"]
    if corruption == "overflow" and kind == "upcoming":
        # Upcoming overflow is evaluation-day arithmetic, not due-date grace.
        occ.api.clock.now = occ.api.clock.now.replace(year=9999, month=12, day=30)
        from app.models.auth_session import AuthSession

        with occ.api.factory.begin() as db:
            for session in db.scalars(
                select(AuthSession).where(AuthSession.user_id == occ.users["A"])
            ):
                session.access_expires_at = occ.api.clock.now.replace(day=31)
                session.refresh_expires_at = session.access_expires_at
    unavailable(occ.query(kind))


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
def test_unrelated_corruption_does_not_leak(occ, kind):
    with occ.api.factory.begin() as db:
        term = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(occ.identifier)
            )
        )
        term.schedule_definition = None
    assert items(occ.query(kind, "C")) == []


def test_lookahead_corruption_fails_page(occ):
    ids = occ.bulk(1, due="2026-09-12")
    with occ.api.factory.begin() as db:
        term = db.scalar(
            select(CommitmentTermsVersion).where(CommitmentTermsVersion.commitment_id == ids[0])
        )
        term.schedule_definition = None
    unavailable(occ.query(params={"limit": 1}))


def test_missing_counterparty_projection(occ, monkeypatch):
    import app.summary_occurrences as service

    original = service.select

    def select_with_missing_projection(*entities, **kwargs):
        query = original(*entities, **kwargs)
        if (
            len(entities) == 2
            and entities[0] is service.User.id
            and entities[1] is service.User.display_name
        ):
            query = query.where(service.User.id != occ.users["B"])
        return query

    monkeypatch.setattr(service, "select", select_with_missing_projection)
    unavailable(occ.query())


def test_defensive_impossible_participant_relationship(occ):
    from sqlalchemy import event
    from sqlalchemy.orm.attributes import set_committed_value

    # The database prevents this persisted state; also exercise the read guard
    # without removing constraints or accidentally writing corrupt fixture rows.
    def corrupt_loaded_parent(parent, context):
        set_committed_value(parent, "lender_user_id", parent.borrower_user_id)

    event.listen(Commitment, "load", corrupt_loaded_parent)
    try:
        unavailable(occ.query())
    finally:
        event.remove(Commitment, "load", corrupt_loaded_parent)


def test_current_version_highest_effective_not_highest_created(occ):
    with occ.api.factory.begin() as db:
        old = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(occ.identifier)
            )
        )
        db.add(
            CommitmentTermsVersion(
                commitment_id=old.commitment_id,
                version_no=2,
                effective_at=occ.api.clock.now + timedelta(seconds=1),
                due_date=date(2026, 12, 10),
                interest_type="NONE",
                grace_period_days=0,
                schedule_definition={
                    "schedule_mode": "single",
                    "due_timezone": "UTC",
                    "installment_dates": None,
                },
                created_by_user_id=occ.users["A"],
            )
        )
    assert items(occ.query())[0]["due_date"] == "2026-09-11"
