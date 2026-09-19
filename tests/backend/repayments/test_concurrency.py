from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.user import User
from sqlalchemy import event, func, select


@pytest.mark.parametrize("same_key", [True, False])
@pytest.mark.parametrize("different_actor", [True, False])
def test_competing_reports_never_overreserve(b7, same_key, different_actor):
    barrier = Barrier(2)

    def run(i):
        barrier.wait(timeout=10)
        return b7.report(
            key="same" if same_key else str(i),
            actor="B" if i and different_actor else "A",
            amount_minor=6000,
        )

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, range(2)))
    assert all(r.status_code in (201, 409) for r in results)
    assert any(r.status_code == 201 for r in results)
    with b7.api.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(LedgerEvent)
                .where(
                    LedgerEvent.commitment_id == UUID(b7.identifier),
                    LedgerEvent.event_type == "REPAYMENT_REPORTED",
                )
            )
            == 1
        )
        ids = select(Repayment.id).where(Repayment.commitment_id == UUID(b7.identifier))
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.object_id.in_(ids), AuditLog.action == "REPAYMENT_REPORTED")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Repayment)
                .where(Repayment.commitment_id == UUID(b7.identifier))
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.sum(Repayment.amount_minor)).where(
                    Repayment.commitment_id == UUID(b7.identifier)
                )
            )
            == 6000
        )
    if not same_key or different_actor:
        assert sorted(r.status_code for r in results) == [201, 409]
        assert (
            next(r for r in results if r.status_code == 409).json()["error"]["code"]
            == "OVER_REPAYMENT"
        )


def test_same_key_inflight_then_replay(b7):
    entered, release = Event(), Event()

    def hold(*args):
        entered.set()
        assert release.wait(10)

    event.listen(Repayment, "before_insert", hold)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(b7.report, key="inflight")
            try:
                assert entered.wait(10)
                duplicate = b7.report(key="inflight")
                assert duplicate.status_code == 409
                assert duplicate.json()["error"]["code"] == "CONFLICT"
            finally:
                release.set()
            original = future.result(timeout=15)
        assert original.status_code == 201
        assert b7.report(key="inflight").json() == original.json()
    finally:
        release.set()
        event.remove(Repayment, "before_insert", hold)


@pytest.mark.parametrize("kind", ["reporter", "counterparty", "state", "terms"])
def test_current_state_wins_after_lock_wait(b7, kind):
    reached = Event()
    engine = b7.api.factory.kw["bind"]
    table = "users" if kind in ("reporter", "counterparty") else "commitments"

    def observe(connection, cursor, statement, parameters, context, executemany):
        if "FROM " + table in statement and "FOR UPDATE" in statement:
            reached.set()

    with b7.api.factory.begin() as writer:
        model, identifier = (
            (User, b7.users["A" if kind == "reporter" else "B"])
            if table == "users"
            else (Commitment, UUID(b7.identifier))
        )
        row = writer.scalar(select(model).where(model.id == identifier).with_for_update())
        event.listen(engine, "before_cursor_execute", observe)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(b7.report)
            try:
                assert reached.wait(10)
                if kind == "terms":
                    from app.models.commitment_terms_version import CommitmentTermsVersion

                    terms = writer.scalar(
                        select(CommitmentTermsVersion).where(
                            CommitmentTermsVersion.commitment_id == identifier
                        )
                    )
                    terms.schedule_definition = {"bad": True}
                else:
                    row.status = "DEACTIVATED" if table == "users" else "CLOSED"
                writer.commit()
                result = future.result(timeout=15)
            finally:
                writer.rollback()
                event.remove(engine, "before_cursor_execute", observe)
    assert (
        result.status_code
        == {"reporter": 403, "counterparty": 404, "state": 409, "terms": 503}[kind]
    )


@pytest.mark.parametrize("actor", ["A", "B"])
def test_report_races_real_b2_deactivation(b7, actor):
    barrier = Barrier(2)

    def report():
        barrier.wait(timeout=10)
        return b7.report()

    def deactivate():
        barrier.wait(timeout=10)
        return b7.api.client.post("/api/v1/me/deactivate", headers=b7.headers[actor])

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(report), pool.submit(deactivate)
        assert first.result(timeout=15).status_code == 201
        result = second.result(timeout=15)
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "ACCOUNT_HAS_UNRESOLVED_COMMITMENTS"


def test_mutation_lock_order_and_no_connection_lock(b7):
    trace = []
    active = False
    engine = b7.api.factory.kw["bind"]

    def observe(connection, cursor, statement, parameters, context, executemany):
        nonlocal active
        if "pg_try_advisory_xact_lock" in statement:
            active = True
        if active and "FOR UPDATE" in statement:
            trace.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert b7.report(actor="B").status_code == 201
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert all("FROM users" in entry[0] for entry in trace[:2])
    assert [next(iter(entry[1].values())) for entry in trace[:2]] == sorted(
        [b7.users["A"], b7.users["B"]]
    )
    assert "FROM commitments" in trace[-1][0]
    assert not any("FROM connections" in entry[0] for entry in trace)
