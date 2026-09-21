from copy import deepcopy
from datetime import date, timedelta
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion as Terms
from app.models.extension_request import ExtensionRequest
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from app.models.user import User
from app.repayments import repayment_accounting
from sqlalchemy import select

from .conftest import requested


def versions(env):
    with env.api.factory() as db:
        return [
            dict(r._mapping)
            for r in db.execute(
                select(Terms.__table__)
                .where(Terms.commitment_id == UUID(env.identifier))
                .order_by(Terms.version_no)
            )
        ]


def extra_version(env, *, future=False):
    old = versions(env)[0]
    with env.api.factory.begin() as db:
        row = Terms(**{k: deepcopy(v) for k, v in old.items() if k != "id"})
        row.version_no = 7
        row.effective_at = env.api.clock.now + timedelta(days=1) if future else env.api.clock.now
        db.add(row)
        db.flush()
        return row.id


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_immutable_versions_and_immediate_effect(b10, action):
    before = versions(b10)
    identifier = requested(b10)
    assert versions(b10) == before
    b10.api.clock.now += timedelta(seconds=30)
    assert b10.decide(identifier, action).status_code == 200
    after = versions(b10)
    assert after[0] == before[0]
    assert len(after) == (2 if action == "accept" else 1)
    if action == "accept":
        new = after[-1]
        assert new["version_no"] == 2
        assert new["effective_at"] == new["created_at"] == b10.api.clock.now
        assert new["created_by_user_id"] == b10.users["B"]
        assert new["due_date"] == date(2026, 11, 10)
        for key in (
            "interest_type",
            "interest_rate_bps",
            "grace_period_days",
            "schedule_definition",
        ):
            assert new[key] == before[0][key]
        with b10.api.factory() as db:
            current, _ = repayment_accounting(
                db, db.get(Commitment, UUID(b10.identifier)), b10.api.clock.now
            )
            assert current == new["id"]


def test_max_includes_future_versions(b10):
    extra_version(b10, future=True)
    identifier = requested(b10)
    assert b10.decide(identifier).status_code == 200
    assert [v["version_no"] for v in versions(b10)] == [1, 7, 8]


def test_stale_base_conflict_without_rebase(b10):
    identifier = requested(b10)
    extra_version(b10)
    result = b10.decide(identifier)
    assert result.status_code == 409 and result.json()["error"]["code"] == "CONFLICT"
    assert b10.read().json()[0]["status"] == "REQUESTED"
    assert len(versions(b10)) == 2
    assert b10.decide(identifier, "reject").status_code == 200


@pytest.mark.parametrize(
    "base,later,code",
    [
        ("2026-10-10", "2026-10-09", 422),
        ("2026-10-10", "2026-10-10", 422),
        ("2026-10-10", "2026-10-11", 201),
        ("2026-01-01", "2026-02-01", 201),
        ("2028-02-28", "2028-02-29", 201),
        ("2028-02-29", "2028-03-01", 201),
    ],
)
def test_calendar_dates(b10, base, later, code):
    with b10.api.factory.begin() as db:
        db.scalar(
            select(Terms).where(Terms.commitment_id == UUID(b10.identifier))
        ).due_date = date.fromisoformat(base)
        db.get(User, b10.users["A"]).timezone = "Pacific/Kiritimati"
        db.get(User, b10.users["B"]).timezone = "America/Los_Angeles"
    response = b10.create(actor="B", requested_due_date=later)
    assert response.status_code == code
    if code == 201:
        assert response.json()["previous_due_date"] == base
        assert b10.decide(response.json()["id"], actor="A").json()["requested_due_date"] == later


@pytest.mark.parametrize(
    "terms",
    [
        {"interest_type": "NONE"},
        {"installment_dates": ["2026-10-10", "2026-11-10"], "interest_type": "NONE"},
    ],
)
def test_unsupported_schedule_untouched(b10, terms):
    parent = b10.commitment(terms=terms)
    with b10.api.factory() as db:
        before = list(
            db.execute(select(CommitmentInstallment.__table__).order_by(CommitmentInstallment.id))
        )
    response = b10.create(parent=parent)
    assert response.status_code == 409 and response.json()["error"]["code"] == "INVALID_STATE"
    with b10.api.factory() as db:
        assert (
            list(
                db.execute(
                    select(CommitmentInstallment.__table__).order_by(CommitmentInstallment.id)
                )
            )
            == before
        )


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_pending_and_lifecycle(b10, action):
    assert b10.read().json() == []
    identifier = requested(b10)
    response = b10.create(actor="B")
    assert response.status_code == 409 and response.json()["error"]["code"] == "CONFLICT"
    assert b10.decide(identifier, action).status_code == 200
    for repeat in ("accept", "reject"):
        assert b10.decide(identifier, repeat).json()["error"]["code"] == "INVALID_STATE"
    requested(b10, actor="B", requested_due_date="2026-12-10")
    rows = b10.read().json()
    assert len(rows) == 2
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    assert rows == b10.read("B").json()


def test_list_newest_first_and_current_names(b10):
    old = requested(b10)
    assert b10.decide(old, "reject").status_code == 200
    b10.api.clock.now += timedelta(seconds=1)
    new = requested(b10)
    with b10.api.factory.begin() as db:
        db.get(User, b10.users["A"]).display_name = "Current requester"
        db.get(User, b10.users["B"]).display_name = "Current decider"
    rows = b10.read().json()
    assert [r["id"] for r in rows] == [new, old]
    assert rows[0]["requested_by"]["display_name"] == "Current requester"
    assert rows[1]["decided_by"]["display_name"] == "Current decider"


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_accounting_and_history_preserved(b10, action):
    first = b10.report(parent=b10.identifier).json()["id"]
    assert b10.financial.decide(identifier=first).status_code == 200
    pending = b10.report(parent=b10.identifier).json()["id"]
    disputed = b10.report(parent=b10.identifier).json()["id"]
    assert b10.financial.decide("dispute", identifier=disputed).status_code == 200
    models = (Repayment, RepaymentVerification, CommitmentInstallment, Commitment)

    def snapshot():
        with b10.api.factory() as db:
            values = {
                m.__name__: list(db.execute(select(m.__table__).order_by(m.id))) for m in models
            }
            _, capacity = repayment_accounting(
                db, db.get(Commitment, UUID(b10.identifier)), b10.api.clock.now
            )
            return values, capacity

    before = snapshot()
    assert before[1].obligation == 10500 and before[1].pending == 1000
    assert before[1].verified_outstanding == 9500
    identifier = requested(b10)
    assert b10.decide(identifier, action).status_code == 200
    assert snapshot() == before
    assert b10.financial.decide(identifier=pending).status_code == 200
    with b10.api.factory() as db:
        event = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.repayment_id == UUID(pending),
                LedgerEvent.event_type == "REPAYMENT_VERIFIED",
            )
        )
        assert event.terms_version_id == versions(b10)[-1]["id"]


@pytest.mark.parametrize(
    "corruption", ["missing_context", "extra_context", "other_base", "invalid_date", "requester"]
)
def test_corrupt_base_fails_safely(b10, corruption):
    identifier = requested(b10)
    with b10.api.factory.begin() as db:
        row = db.get(ExtensionRequest, UUID(identifier))
        if corruption == "missing_context":
            row.requested_terms = None
        elif corruption == "extra_context":
            row.requested_terms = {**row.requested_terms, "secret": "private"}
        elif corruption == "other_base":
            other = db.scalar(
                select(Terms).where(Terms.commitment_id == UUID(b10.financial.identifier))
            )
            row.requested_terms = {"base_terms_version_id": str(other.id)}
        elif corruption == "invalid_date":
            row.requested_due_date = date(2020, 1, 1)
        else:
            row.requested_by_user_id = b10.users["C"]
    assert b10.read().status_code == 503
    assert b10.decide(identifier).status_code == 503
