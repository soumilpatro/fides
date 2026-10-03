from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from app import reminders
from app.models.commitment import Commitment
from app.models.user import User
from app.reminders import candidates, dedupe_key, insert_candidate, snapshot_query
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from repayments.conftest import seed


def test_exact_key():
    a, b, i = uuid4(), uuid4(), uuid4()
    for installment in (None, i):
        key = dedupe_key(a, "OVERDUE", b, installment, date(2026, 9, 11))
        assert key == f"r1|{a}|OVERDUE|{b}|{installment or '-'}|2026-09-11"
        assert len(key) <= 160


@pytest.mark.parametrize("kind", ["UPCOMING_DUE", "DUE_TODAY", "OVERDUE"])
def test_overlapping_workers(env, kind, monkeypatch):
    env.configure(
        {"UPCOMING_DUE": "2026-09-14", "DUE_TODAY": "2026-09-11", "OVERDUE": "2026-09-10"}[kind]
    )
    barrier = Barrier(2)
    original = reminders.candidates

    def together(row, now):
        result = original(row, now)
        if row.Commitment.id == env.parent_id:
            barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(reminders, "candidates", together)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: env.job.run(now=env.api.clock.now), range(2)))
    expected = 2 if kind == "OVERDUE" else 1
    assert sum(r["created"] for r in results) == expected
    assert len(env.rows()) == expected


@pytest.mark.parametrize("change", ["preference", "verified", "extension", "deactivated", "closed"])
def test_execution_recheck_after_committed_change(env, change):
    with env.api.factory.begin() as db:
        query = snapshot_query([env.parent_id], env.api.clock.now)
        row = db.execute(query).one()
        candidate = candidates(row, env.api.clock.now)[0]
        # A separate committed transaction changes the snapshot before INSERT SELECT.
        if change == "preference":
            assert env.preference(due=False).status_code == 200
        elif change == "extension":
            request = env.create()
            assert env.decide(request.json()["id"]).status_code == 200
        elif change == "verified":
            seed(env, 10500, "VERIFIED")
        else:
            with env.api.factory.begin() as writer:
                if change == "deactivated":
                    writer.get(User, env.users["A"]).status = "DEACTIVATED"
                else:
                    writer.get(Commitment, env.parent_id).status = "CLOSED"
        assert not insert_candidate(db, query, row, candidate, env.api.clock.now)
    assert env.rows() == []


def test_direct_duplicate_and_fk_error(env):
    with env.api.factory.begin() as db:
        query = snapshot_query([env.parent_id], env.api.clock.now)
        row = db.execute(query).one()
        candidate = candidates(row, env.api.clock.now)[0]
        assert insert_candidate(db, query, row, candidate, env.api.clock.now)
        assert not insert_candidate(db, query, row, candidate, env.api.clock.now)
    with pytest.raises(IntegrityError), env.api.factory.begin() as db:
        query = snapshot_query([env.parent_id], env.api.clock.now)
        row = db.execute(query).one()
        candidate = (uuid4(), *candidates(row, env.api.clock.now)[0][1:])
        insert_candidate(db, query, row, candidate, env.api.clock.now)


def test_job_failure_cannot_rollback_financial_action(env, monkeypatch):
    before = env.read("A", parent=env.identifier).json()

    def fail(*args, **kwargs):
        raise RuntimeError("injected reminder failure")

    monkeypatch.setattr(reminders, "insert_candidate", fail)
    with pytest.raises(RuntimeError):
        env.job.run(now=env.api.clock.now)
    assert env.rows() == []
    assert env.read("A", parent=env.identifier).json() == before
    assert env.create().status_code == 201


@pytest.mark.parametrize("model", [Commitment, User])
def test_job_does_not_take_financial_or_user_locks(env, model):
    identifier = env.parent_id if model is Commitment else env.users["A"]
    if model is User:
        # PostgreSQL FK inserts necessarily take a user key-share lock; isolate
        # eligibility reads here so the harness does not deadlock on that FK.
        env.configure("2026-09-15")
    with env.api.factory.begin() as writer:
        writer.scalar(select(model).where(model.id == identifier).with_for_update())
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(env.job.run, now=env.api.clock.now).result(timeout=20)[
                "created"
            ] == (0 if model is User else 1)


def test_database_failure_rolls_back_page(env):
    engine = env.api.factory.kw["bind"]

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO notification_events"):
            raise RuntimeError("injected DB failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError):
            env.job.run(now=env.api.clock.now)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert env.rows() == []
    assert env.job.run(now=env.api.clock.now)["created"] == 1
    assert env.job.run(now=env.api.clock.now)["created"] == 0


def test_real_clock_and_local_day_recheck(env):
    now = datetime.now(UTC)
    env.configure((now.date() + timedelta(days=3)).isoformat())
    assert env.job.run()["created"] == 1
    # A candidate produced for yesterday cannot leak through after local midnight.
    with env.api.factory.begin() as db:
        query = snapshot_query([env.parent_id], now)
        row = db.execute(query).one()
        candidate = candidates(row, now)[0]
        final = snapshot_query([env.parent_id], func.statement_timestamp())
        assert not insert_candidate(
            db, final, row, candidate, now - timedelta(days=1), live_clock=True
        )


def test_extension_after_enumeration_time(env):
    with env.api.factory.begin() as db:
        query = snapshot_query([env.parent_id], env.api.clock.now)
        row = db.execute(query).one()
        candidate = candidates(row, env.api.clock.now)[0]
        env.api.clock.now += timedelta(seconds=1)
        request = env.create()
        assert env.decide(request.json()["id"]).status_code == 200
        final = snapshot_query([env.parent_id], env.api.clock.now)
        assert not insert_candidate(db, final, row, candidate, env.api.clock.now)
