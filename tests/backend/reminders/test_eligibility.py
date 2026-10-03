from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.notification_event import NotificationEvent
from app.models.repayment import Repayment
from app.models.user import User
from app.reminders import REMINDER_TYPES, snapshot_query
from sqlalchemy import select

from repayments.conftest import seed


@pytest.mark.parametrize(
    "due,grace,expected",
    [
        ("2026-09-15", 0, None),
        ("2026-09-14", 0, "UPCOMING_DUE"),
        ("2026-09-13", 0, None),
        ("2026-09-12", 0, None),
        ("2026-09-11", 0, "DUE_TODAY"),
        ("2026-09-10", 0, "OVERDUE"),
        ("2026-09-10", 3, None),
        ("2026-09-07", 3, "OVERDUE"),
    ],
)
def test_calendar_boundary(env, due, grace, expected):
    env.configure(due, grace)
    result = env.job.run(now=env.api.clock.now)
    assert result["failed_candidates"] == 0
    rows = env.rows()
    assert {r.type for r in rows} == ({expected} if expected else set())
    assert {r.user_id for r in rows} == (
        {env.users["A"], env.users["B"]}
        if expected == "OVERDUE"
        else {env.users["A"]}
        if expected
        else set()
    )


@pytest.mark.parametrize(
    "due,expected",
    [
        ("2026-09-10", "2026-09-11"),
        ("2026-09-09", "2026-09-10"),
        ("2026-09-03", "2026-09-11"),
        ("2026-08-20", "2026-09-11"),
        ("2026-08-19", "2026-09-10"),
    ],
)
def test_only_current_overdue_window(env, due, expected):
    env.configure(due)
    assert env.job.run(now=env.api.clock.now)["created"] == 2
    assert {r.payload["scheduled_local_date"] for r in env.rows()} == {expected}
    assert env.job.run(now=env.api.clock.now)["created"] == 0


@pytest.mark.parametrize(
    "status", ["PENDING_CONFIRMATION", "REJECTED", "CANCELLED", "FULLY_REPAID", "CLOSED"]
)
def test_ineligible_states(env, status):
    env.configure(status=status)
    assert env.job.run(now=env.api.clock.now)["created"] == 0


def test_no_deadline(env):
    env.configure(None)
    assert env.job.run(now=env.api.clock.now) == {"created": 0, "failed_candidates": 0}


@pytest.mark.parametrize(
    "status,amount,expected",
    [
        ("PENDING_VERIFICATION", 10500, 1),
        ("DISPUTED", 10500, 1),
        ("VERIFIED", 1000, 1),
        ("VERIFIED", 10500, 0),
    ],
)
def test_verified_accounting(env, status, amount, expected):
    with env.api.factory.begin() as db:
        db.get(Repayment, UUID(env.repayment)).status = "DISPUTED"
    seed(env, amount, status)
    assert env.job.run(now=env.api.clock.now)["created"] == expected


@pytest.mark.parametrize(
    "actor,gate,expected",
    [
        ("A", "due", 0),
        ("B", "due", 1),
        ("A", "overdue", 1),
        ("B", "overdue", 1),
    ],
)
def test_recipient_preferences(env, actor, gate, expected):
    if gate == "overdue":
        env.configure("2026-09-10")
    assert env.preference(actor, **{gate: False}).status_code == 200
    assert env.job.run(now=env.api.clock.now)["created"] == expected
    if actor == "A" or gate == "overdue":
        assert env.users[actor] not in {r.user_id for r in env.rows()}


def test_reenabled_no_stale_due_backfill(env):
    env.configure("2026-09-11", grace=3)
    env.preference(due=False)
    assert env.job.run(now=env.api.clock.now)["created"] == 0
    env.preference(due=True)
    assert env.job.run(now=datetime(2026, 9, 12, 12, tzinfo=UTC))["created"] == 0


def test_reenabled_current_overdue_only(env):
    env.configure("2026-08-20")
    env.preference(overdue=False)
    assert env.job.run(now=env.api.clock.now)["created"] == 1
    env.preference(overdue=True)
    assert env.job.run(now=env.api.clock.now)["created"] == 1
    assert len(env.rows()) == 2


@pytest.mark.parametrize(
    "timezone,stamp,expected",
    [
        ("Pacific/Kiritimati", "2026-09-10T12:00:00+00:00", "UPCOMING_DUE"),
        ("America/Los_Angeles", "2026-09-11T02:00:00+00:00", None),
        ("Asia/Kolkata", "2026-09-10T20:00:00+00:00", "UPCOMING_DUE"),
    ],
)
def test_contractual_timezone(env, timezone, stamp, expected):
    env.configure(timezone=timezone)
    with env.api.factory.begin() as db:
        db.get(User, env.users["A"]).timezone = "Europe/London"
        term = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == env.parent_id
            )
        )
        term.effective_at = datetime(2026, 9, 1, tzinfo=UTC)
    env.job.run(now=datetime.fromisoformat(stamp))
    assert {r.type for r in env.rows()} == ({expected} if expected else set())


def test_extension_current_terms_and_history(env):
    assert env.job.run(now=env.api.clock.now)["created"] == 1
    response = env.create()
    assert response.status_code == 201
    assert env.decide(response.json()["id"]).status_code == 200
    assert env.job.run(now=env.api.clock.now)["created"] == 0
    response = env.inbox("A")
    assert response.status_code == 200, response.text
    assert any(r["type"] == "UPCOMING_DUE" for r in response.json()["items"])


def test_installment_schedule_only(env):
    identifier = env.commitment(
        terms={"interest_type": "NONE", "installment_dates": ["2026-09-14", "2026-09-21"]}
    )
    env.job.run(now=env.api.clock.now)
    with env.api.factory() as db:
        rows = list(
            db.scalars(
                select(NotificationEvent).where(
                    NotificationEvent.object_id == UUID(identifier),
                    NotificationEvent.type.in_(REMINDER_TYPES),
                )
            )
        )
        installments = list(
            db.scalars(
                select(CommitmentInstallment)
                .where(CommitmentInstallment.commitment_id == UUID(identifier))
                .order_by(CommitmentInstallment.sequence_no)
            )
        )
        assert len(rows) == 1
        assert rows[0].payload["installment_id"] == str(installments[0].id)
        assert set(rows[0].payload) == {
            "terms_version_id",
            "installment_id",
            "scheduled_local_date",
        }
        assert all(row.status == "PENDING" for row in installments)


@pytest.mark.parametrize("corruption", ["currency", "overpaid", "timezone", "metadata"])
def test_corrupt_candidate_fails_closed(env, corruption):
    if corruption in ("currency", "overpaid"):
        seed(
            env,
            999999 if corruption == "overpaid" else 1000,
            "VERIFIED" if corruption == "overpaid" else "PENDING_VERIFICATION",
            currency="USD" if corruption == "currency" else "INR",
        )
    with env.api.factory.begin() as db:
        if corruption not in ("currency", "overpaid"):
            term = db.scalar(
                select(CommitmentTermsVersion).where(
                    CommitmentTermsVersion.commitment_id == env.parent_id
                )
            )
            term.schedule_definition = {
                **term.schedule_definition,
                **({"due_timezone": "not-a-zone"} if corruption == "timezone" else {"extra": True}),
            }
    result = env.job.run(now=env.api.clock.now)
    assert result["failed_candidates"] == 1
    assert result["created"] == 0


def test_batched_snapshot_inputs(env):
    seed(env, 1000, "PENDING_VERIFICATION")
    with env.api.factory.begin() as db:
        row = db.execute(snapshot_query([env.parent_id], env.api.clock.now)).one()
        assert row.Commitment.id == env.parent_id
        assert row.sums["PENDING_VERIFICATION"] == 1000
        assert row.borrower_due and row.lender_overdue


def test_keyset_pages_cover_all_eligible_parents(env):
    env.commitment(terms={"interest_type": "NONE", "due_date": "2026-09-14"})
    result = env.job.run(now=env.api.clock.now, page_size=1)
    assert result == {"created": 2, "failed_candidates": 0}
    assert env.job.run(now=env.api.clock.now, page_size=1)["created"] == 0


@pytest.mark.parametrize("corruption", ["association", "too_many"])
def test_corrupt_installments_bounded_and_closed(env, corruption):
    identifier = env.commitment(
        terms={
            "interest_type": "NONE",
            "installment_dates": ["2026-09-14", "2026-09-21"],
        }
    )
    with env.api.factory.begin() as db:
        rows = list(
            db.scalars(
                select(CommitmentInstallment)
                .where(CommitmentInstallment.commitment_id == UUID(identifier))
                .order_by(CommitmentInstallment.sequence_no)
            )
        )
        if corruption == "association":
            rows[0].commitment_id = env.parent_id
        else:
            for sequence in range(3, 63):
                db.add(
                    CommitmentInstallment(
                        commitment_id=UUID(identifier),
                        terms_version_id=rows[0].terms_version_id,
                        due_date=rows[-1].due_date,
                        sequence_no=sequence,
                        principal_amount_minor=1,
                        interest_amount_minor=0,
                        total_due_minor=1,
                        status="PENDING",
                    )
                )
    with env.api.factory() as db:
        snapshots = list(
            db.execute(snapshot_query([env.parent_id, UUID(identifier)], env.api.clock.now))
        )
        if corruption == "too_many":
            assert max(len(row.schedule) for row in snapshots) == 61
    result = env.job.run(now=env.api.clock.now)
    assert result == {"created": 1, "failed_candidates": 1}
