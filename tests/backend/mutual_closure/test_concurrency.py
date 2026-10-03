from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from app.models.connection import Connection
from app.models.extension_request import ExtensionRequest
from app.models.ledger_event import LedgerEvent
from app.models.mutual_closure_request import MutualClosureRequest
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from sqlalchemy import event, func, select

from .conftest import error, requested
from .test_integration import dated


def race(*actions):
    barrier = Barrier(len(actions))

    def run(action):
        barrier.wait(timeout=15)
        return action()

    with ThreadPoolExecutor(len(actions)) as pool:
        return [f.result(timeout=30) for f in [pool.submit(run, a) for a in actions]]


def ordered(mc, first, second, model, hook):
    """Hold the first writer inside flush with its locks until the second waits on Users."""
    entered, release, waiting = Event(), Event(), Event()
    engine = mc.api.factory.kw["bind"]

    def hold(*args):
        entered.set()
        assert release.wait(20)

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            waiting.set()

    event.listen(model, hook, hold)
    try:
        with ThreadPoolExecutor(2) as pool:
            left = pool.submit(first)
            try:
                assert entered.wait(15)
                event.listen(engine, "before_cursor_execute", observe)
                right = pool.submit(second)
                assert waiting.wait(15)
            finally:
                release.set()
            results = left.result(timeout=30), right.result(timeout=30)
    finally:
        release.set()
        event.remove(model, hook, hold)
        if event.contains(engine, "before_cursor_execute", observe):
            event.remove(engine, "before_cursor_execute", observe)
    return results


def test_simultaneous_create(mc):
    results = race(mc.create, lambda: mc.create(actor="B"))
    assert sorted(r.status_code for r in results) == [201, 409]
    error(next(r for r in results if r.status_code == 409), "CONFLICT")
    assert len(mc.closure_read().json()) == 1


@pytest.mark.parametrize("action,actor", [("accept", "B"), ("reject", "B"), ("cancel", "A")])
@pytest.mark.parametrize("first_accept", [True, False])
def test_terminal_transition_races(mc, action, actor, first_accept):
    identifier = requested(mc)

    def left():
        return mc.decide(identifier)

    def right():
        return mc.decide(identifier, action, actor=actor)

    if not first_accept:
        left, right = right, left
    winner, loser = ordered(mc, left, right, MutualClosureRequest, "before_update")
    assert winner.status_code == 200
    error(loser, "INVALID_STATE")
    with mc.api.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(LedgerEvent)
                .where(
                    LedgerEvent.commitment_id == UUID(mc.identifier),
                    LedgerEvent.event_type.like("MUTUAL_CLOSURE_%"),
                )
            )
            == 2
        )


@pytest.mark.parametrize("report_first", [True, False])
def test_report_accept_serialization(mc, report_first):
    identifier = requested(mc)
    first = mc.report if report_first else lambda: mc.decide(identifier)
    second = (lambda: mc.decide(identifier)) if report_first else mc.report
    results = ordered(
        mc,
        first,
        second,
        Repayment if report_first else MutualClosureRequest,
        "before_insert" if report_first else "before_update",
    )
    assert results[0].status_code == (201 if report_first else 200)
    error(results[1], "CONFLICT" if report_first else "INVALID_STATE")


@pytest.mark.parametrize("amount", [1000, 10000])
def test_verification_first(mc, amount):
    identifier = requested(mc)
    repayment = mc.report(amount_minor=amount).json()["id"]
    first, second = ordered(
        mc,
        lambda: mc.verify(repayment),
        lambda: mc.decide(identifier),
        RepaymentVerification,
        "before_insert",
    )
    assert first.status_code == 200
    error(second, "CONFLICT" if amount < 10000 else "INVALID_STATE")


def test_accept_cannot_win_with_pending_verification(mc):
    identifier = requested(mc)
    repayment = mc.report().json()["id"]
    results = race(lambda: mc.decide(identifier), lambda: mc.verify(repayment))
    error(results[0], "CONFLICT")
    assert results[1].status_code == 200


def test_dispute_first_releases_reservation(mc):
    identifier = requested(mc)
    repayment = mc.report().json()["id"]
    results = ordered(
        mc,
        lambda: mc.verify(repayment, "dispute"),
        lambda: mc.decide(identifier),
        RepaymentVerification,
        "before_insert",
    )
    assert [r.status_code for r in results] == [200, 200]
    assert results[1].json()["waived_amount_minor"] == 10000


def test_accept_before_dispute_returns_conflict_then_retry(mc):
    identifier = requested(mc)
    repayment = mc.report().json()["id"]
    error(mc.decide(identifier), "CONFLICT")
    assert mc.verify(repayment, "dispute").status_code == 200
    assert mc.decide(identifier).status_code == 200


@pytest.mark.parametrize("extension_first", [True, False])
def test_extension_accept_serialization(mc, extension_first):
    dated(mc)
    eid = mc.extension().json()["id"]
    identifier = requested(mc)
    first = (lambda: mc.extension(eid)) if extension_first else lambda: mc.decide(identifier)
    second = (lambda: mc.decide(identifier)) if extension_first else lambda: mc.extension(eid)
    results = ordered(
        mc,
        first,
        second,
        ExtensionRequest if extension_first else MutualClosureRequest,
        "before_update",
    )
    assert results[0].status_code == 200
    if extension_first:
        assert results[1].status_code == 200
    else:
        error(results[1], "INVALID_STATE")


@pytest.mark.parametrize("action", ["create", "accept", "reject", "cancel"])
def test_same_key_overlap(mc, action):
    identifier = None if action == "create" else requested(mc)

    def call():
        return (
            mc.create(key="inflight")
            if action == "create"
            else mc.decide(
                identifier, action, actor="A" if action == "cancel" else "B", key="inflight"
            )
        )

    entered, release = Event(), Event()

    def hold(*args):
        entered.set()
        assert release.wait(20)

    hook = "before_insert" if action == "create" else "before_update"
    event.listen(MutualClosureRequest, hook, hold)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(call)
            try:
                assert entered.wait(15)
                error(call(), "CONFLICT")
            finally:
                release.set()
            original = future.result(timeout=30)
        assert original.status_code == (201 if action == "create" else 200)
        assert call().json() == original.json()
    finally:
        release.set()
        event.remove(MutualClosureRequest, hook, hold)


def test_existing_lock_hierarchy(mc):
    identifier = requested(mc)
    trace = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement or "pg_try_advisory_xact_lock" in statement:
            trace.append((statement, parameters))

    engine = mc.api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert mc.decide(identifier).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert "pg_try_advisory_xact_lock" in trace[0][0]
    assert all("FROM users" in s for s, _ in trace[1:3])
    assert [next(iter(p.values())) for _, p in trace[1:3]] == sorted([mc.users["A"], mc.users["B"]])
    assert "FROM commitments" in trace[-2][0] and "FROM mutual_closure_requests" in trace[-1][0]
    assert not any(
        "FROM connections" in s or "FROM repayments" in s or "FROM commitment_terms_versions" in s
        for s, _ in trace
    )


def test_no_connection_lock(mc):
    with mc.api.factory.begin() as writer:
        writer.scalar(
            select(Connection).where(Connection.id == UUID(mc.connection)).with_for_update()
        )
        with ThreadPoolExecutor(1) as pool:
            result = pool.submit(mc.create).result(timeout=15)
        assert result.status_code == 201
