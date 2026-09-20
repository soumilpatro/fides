from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from app.models.user import User
from sqlalchemy import event, func, select

from .conftest import seed


@pytest.mark.parametrize(
    "actions", [("verify", "verify"), ("verify", "dispute"), ("dispute", "dispute")]
)
def test_one_authoritative_decision(b8, actions):
    barrier = Barrier(2)

    def decide(i):
        barrier.wait(timeout=10)
        return b8.decide(actions[i], key=str(i))

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(decide, range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json()["status"] for r in results if r.status_code == 200)
    loser = next(r.json()["error"]["code"] for r in results if r.status_code == 409)
    assert loser == ("ALREADY_VERIFIED" if winner == "VERIFIED" else "INVALID_STATE")
    with b8.api.factory() as db:
        assert db.get(Repayment, UUID(b8.repayment)).status.value == winner
        for model, predicate in [
            (RepaymentVerification, RepaymentVerification.repayment_id == UUID(b8.repayment)),
            (
                LedgerEvent,
                (LedgerEvent.repayment_id == UUID(b8.repayment))
                & LedgerEvent.event_type.in_(["REPAYMENT_VERIFIED", "REPAYMENT_DISPUTED"]),
            ),
            (
                AuditLog,
                (AuditLog.object_id == UUID(b8.repayment))
                & AuditLog.action.in_(["REPAYMENT_VERIFIED", "REPAYMENT_DISPUTED"]),
            ),
        ]:
            assert db.scalar(select(func.count()).select_from(model).where(predicate)) == 1


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_same_key_inflight_then_replay(b8, action):
    entered, release = Event(), Event()

    def hold(*args):
        entered.set()
        assert release.wait(10)

    event.listen(RepaymentVerification, "before_insert", hold)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(b8.decide, action, key="inflight")
            try:
                assert entered.wait(10)
                result = b8.decide(action, key="inflight")
                assert result.status_code == 409
                assert result.json()["error"]["code"] == "CONFLICT"
            finally:
                release.set()
            original = future.result(timeout=15)
        assert original.status_code == 200
        assert b8.decide(action, key="inflight").json() == original.json()
        assert len(b8.history().json()) == 1
    finally:
        release.set()
        event.remove(RepaymentVerification, "before_insert", hold)


def test_distinct_reports_cannot_both_overcredit(b8):
    with b8.api.factory.begin() as db:
        db.get(Repayment, UUID(b8.repayment)).amount_minor = 6000
    second = seed(b8, 6000, "PENDING_VERIFICATION")
    barrier = Barrier(2)

    def decide(identifier):
        barrier.wait(timeout=10)
        return b8.decide(identifier=identifier)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(decide, [b8.repayment, second]))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert (
        next(r.json()["error"]["code"] for r in results if r.status_code == 409) == "OVER_REPAYMENT"
    )
    with b8.api.factory() as db:
        assert (
            db.scalar(
                select(func.sum(Repayment.amount_minor)).where(
                    Repayment.commitment_id == UUID(b8.identifier), Repayment.status == "VERIFIED"
                )
            )
            == 6000
        )


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_report_and_decision_serialize(b8, action):
    # Request the full original obligation: it fits only after dispute releases Q.
    barrier = Barrier(2)

    def decide():
        barrier.wait(timeout=10)
        return b8.decide(action)

    def report():
        barrier.wait(timeout=10)
        return b8.report(amount_minor=10000)

    with ThreadPoolExecutor(2) as pool:
        decision, reporting = pool.submit(decide), pool.submit(report)
        assert decision.result(timeout=15).status_code == 200
        result = reporting.result(timeout=15)
    assert result.status_code in ((409,) if action == "verify" else (201, 409))
    if result.status_code == 409:
        assert result.json()["error"]["code"] == "OVER_REPAYMENT"
        if action == "dispute":
            assert b8.report(amount_minor=10000).status_code == 201
    with b8.api.factory() as db:
        assert (
            db.scalar(
                select(func.sum(Repayment.amount_minor)).where(
                    Repayment.commitment_id == UUID(b8.identifier),
                    Repayment.status.in_(["VERIFIED", "PENDING_VERIFICATION"]),
                )
            )
            <= 10000
        )


@pytest.mark.parametrize(
    "kind", ["actor", "counterparty", "parent", "repayment", "terms", "reporter", "association"]
)
def test_recheck_after_lock_wait(b8, kind):
    reached = Event()
    engine = b8.api.factory.kw["bind"]
    table = "users" if kind in ("actor", "counterparty", "reporter") else "commitments"
    other_parent = b8.commitment() if kind == "association" else None

    def observe(connection, cursor, statement, parameters, context, executemany):
        if "FROM " + table in statement and "FOR UPDATE" in statement:
            reached.set()

    with b8.api.factory.begin() as writer:
        if kind == "reporter":
            # A reporter FK update takes a User key-share lock. The synthetic
            # writer must follow the same User-before-parent order as B8.
            for user_id in sorted([b8.users["A"], b8.users["B"]]):
                writer.scalar(select(User.id).where(User.id == user_id).with_for_update())
        model, identifier = (
            (User, b8.users["B" if kind == "actor" else "A"])
            if table == "users"
            else (Commitment, UUID(b8.identifier))
        )
        locked = writer.scalar(select(model).where(model.id == identifier).with_for_update())
        if kind == "reporter":
            writer.scalar(
                select(Commitment.id).where(Commitment.id == UUID(b8.identifier)).with_for_update()
            )
        event.listen(engine, "before_cursor_execute", observe)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(b8.decide)
            try:
                assert reached.wait(10)
                if kind in ("actor", "counterparty"):
                    locked.status = "DEACTIVATED"
                elif kind == "parent":
                    locked.status = "CLOSED"
                elif kind == "terms":
                    writer.scalar(
                        select(CommitmentTermsVersion).where(
                            CommitmentTermsVersion.commitment_id == identifier
                        )
                    ).schedule_definition = {"bad": True}
                else:
                    row = writer.get(Repayment, UUID(b8.repayment))
                    if kind == "repayment":
                        row.status = "CANCELLED"
                    elif kind == "reporter":
                        row.reported_by_user_id = b8.users["B"]
                    else:
                        row.commitment_id = UUID(other_parent)
                writer.commit()
                result = future.result(timeout=15)
            finally:
                writer.rollback()
                event.remove(engine, "before_cursor_execute", observe)
    assert (
        result.status_code
        == {
            "actor": 403,
            "counterparty": 503,
            "parent": 409,
            "repayment": 409,
            "terms": 503,
            "reporter": 403,
            "association": 404,
        }[kind]
    )
    with b8.api.factory() as db:
        assert not db.scalar(
            select(RepaymentVerification.id).where(
                RepaymentVerification.repayment_id == UUID(b8.repayment)
            )
        )


@pytest.mark.parametrize("actor", ["A", "B"])
def test_real_deactivation_race(b8, actor):
    barrier = Barrier(2)

    def decide():
        barrier.wait(timeout=10)
        return b8.decide()

    def deactivate():
        barrier.wait(timeout=10)
        return b8.api.client.post("/api/v1/me/deactivate", headers=b8.headers[actor])

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(decide), pool.submit(deactivate)
        assert first.result(timeout=15).status_code == 200
        result = second.result(timeout=15)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "ACCOUNT_HAS_UNRESOLVED_COMMITMENTS"


def test_global_mutation_lock_order(b8):
    trace = []
    active = False
    engine = b8.api.factory.kw["bind"]

    def observe(connection, cursor, statement, parameters, context, executemany):
        nonlocal active
        if "pg_try_advisory_xact_lock" in statement:
            active = True
        if active and "FOR UPDATE" in statement:
            trace.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert b8.decide().status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert all("FROM users" in entry[0] for entry in trace[:2])
    assert [next(iter(entry[1].values())) for entry in trace[:2]] == sorted(
        [b8.users["A"], b8.users["B"]]
    )
    assert "FROM commitments" in trace[-2][0]
    assert "FROM repayments" in trace[-1][0]
    assert not any("FROM connections" in entry[0] for entry in trace)


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_terms_version_committed_while_waiting_is_authoritative(b8, action):
    reached = Event()
    engine = b8.api.factory.kw["bind"]

    def observe(connection, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            reached.set()

    with b8.api.factory.begin() as writer:
        # Terms insertion also references a User. Model a compliant future
        # writer rather than introducing a parent-before-User FK deadlock.
        for user_id in sorted([b8.users["A"], b8.users["B"]]):
            writer.scalar(select(User.id).where(User.id == user_id).with_for_update())
        writer.scalar(
            select(Commitment).where(Commitment.id == UUID(b8.identifier)).with_for_update()
        )
        event.listen(engine, "before_cursor_execute", observe)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(b8.decide, action)
            try:
                assert reached.wait(10)
                version = CommitmentTermsVersion(
                    commitment_id=UUID(b8.identifier),
                    version_no=2,
                    effective_at=b8.api.clock.now,
                    interest_type="SIMPLE_FIXED",
                    interest_rate_bps=1000,
                    grace_period_days=0,
                    created_by_user_id=b8.users["A"],
                    schedule_definition={
                        "schedule_mode": "none",
                        "due_timezone": "UTC",
                        "installment_dates": None,
                    },
                )
                writer.add(version)
                writer.flush()
                new_terms_id = version.id
                writer.commit()
                result = future.result(timeout=15)
            finally:
                writer.rollback()
                event.remove(engine, "before_cursor_execute", observe)
    assert result.status_code == 200
    with b8.api.factory() as db:
        ledger = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.repayment_id == UUID(b8.repayment),
                LedgerEvent.event_type
                == ("REPAYMENT_VERIFIED" if action == "verify" else "REPAYMENT_DISPUTED"),
            )
        )
        assert ledger.terms_version_id == (new_terms_id if action == "verify" else None)
        if action == "verify":
            assert ledger.event_payload["verified_outstanding"] == 10000
