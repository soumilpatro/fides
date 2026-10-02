import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.core.reliability import transaction
from app.models.repayment import Repayment
from app.models.user import User
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError

from .helpers import snapshot


@pytest.mark.parametrize("state", ["40P01", "40001", "55P03", "57014", "23505", "08006"])
@pytest.mark.parametrize("location", ["idempotency", "auth_recheck", "resource_lookup"])
def test_postgres_failure_class_safe_rollback_and_no_retry(b10, caplog, state, location):
    engine = b10.api.factory.kw["bind"]
    before = snapshot(b10)
    attempts = []
    b10.headers["A"]["X-Request-ID"] = "b13-failure-class"

    def fail(conn, cursor, sql, params, context, many):
        selected = {
            "idempotency": "pg_try_advisory_xact_lock" in sql,
            "auth_recheck": "FROM users" in sql
            and "users.display_name" in sql
            and "FOR UPDATE" in sql,
            "resource_lookup": "FROM commitments" in sql and "FOR UPDATE" in sql,
        }[location]
        if selected:
            attempts.append(state)
            # Real PostgreSQL errors in the actual financial transaction, not a
            # Python lookalike. Deadlock/serialization here are controlled fault
            # injection; separate tests induce a real deadlock and timeout waits.
            conn.exec_driver_sql(
                "DO $$ BEGIN RAISE EXCEPTION 'private SQL phone token OTP note' "
                f"USING ERRCODE = '{state}'; END $$"
            )

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with caplog.at_level(logging.WARNING, logger="fides.reliability"):
            result = b10.report(parent=b10.identifier, key="failure-class")
        assert result.status_code == 503, result.text
        assert result.headers["X-Request-ID"] == "b13-failure-class"
        assert attempts == [state]
        assert snapshot(b10) == before
        records = [r for r in caplog.records if r.name == "fides.reliability"]
        assert len(records) == 1
        assert records[0].fields["sqlstate"] == state
        assert records[0].fields["request_id"] == "b13-failure-class"
        assert "private" not in result.text + str(records[0].fields)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert b10.report(parent=b10.identifier, key="failure-class").status_code == 201


def test_real_statement_timeout_after_domain_flush(b10):
    before = snapshot(b10)

    def timeout(mapper, conn, row):
        conn.exec_driver_sql("SET LOCAL statement_timeout = '50ms'")
        conn.exec_driver_sql("SELECT pg_sleep(1)")

    event.listen(Repayment, "after_insert", timeout)
    try:
        result = b10.report(parent=b10.identifier, key="statement-timeout")
        assert result.status_code == 503 and snapshot(b10) == before
    finally:
        event.remove(Repayment, "after_insert", timeout)
    assert b10.report(parent=b10.identifier, key="statement-timeout").status_code == 201


def test_real_lock_timeout_on_user_coordination(b10):
    engine = b10.api.factory.kw["bind"]
    before = snapshot(b10)

    def timeout(conn, cursor, sql, params, context, many):
        if "pg_try_advisory_xact_lock" in sql:
            conn.exec_driver_sql("SET LOCAL lock_timeout = '50ms'")

    with b10.api.factory.begin() as writer:
        writer.scalar(select(User).where(User.id == b10.users["A"]).with_for_update())
        event.listen(engine, "before_cursor_execute", timeout)
        try:
            result = b10.report(parent=b10.identifier, key="lock-timeout")
            assert result.status_code == 503
            assert snapshot(b10) == before
        finally:
            event.remove(engine, "before_cursor_execute", timeout)
    assert b10.report(parent=b10.identifier, key="lock-timeout").status_code == 201


def test_connection_loss_before_commit_leaves_no_effects(b10):
    before = snapshot(b10)

    def disconnect(mapper, conn, row):
        conn.connection.driver_connection.close()
        conn.exec_driver_sql("SELECT 1")

    event.listen(Repayment, "after_insert", disconnect)
    try:
        result = b10.report(parent=b10.identifier, key="connection-loss")
        assert result.status_code == 503
        assert snapshot(b10) == before
    finally:
        event.remove(Repayment, "after_insert", disconnect)
    assert b10.report(parent=b10.identifier, key="connection-loss").status_code == 201


def test_real_deadlock_is_aborted_without_statement_retry(b10, caplog):
    # Deliberately reversed locks only in this fault test; production order is
    # independently asserted across every financial route.
    barrier = Barrier(2)
    users = [b10.users["A"], b10.users["B"]]

    def contender(order):
        try:
            with transaction(b10.api.factory, "commitments") as db:
                db.execute(text("SET LOCAL statement_timeout = '5s'"))
                db.scalar(select(User.id).where(User.id == users[order]).with_for_update())
                barrier.wait(10)
                db.scalar(select(User.id).where(User.id == users[1 - order]).with_for_update())
            return "committed"
        except DBAPIError as error:
            return error.orig.sqlstate

    with (
        caplog.at_level(logging.WARNING, logger="fides.reliability"),
        ThreadPoolExecutor(2) as pool,
    ):
        a, b = pool.submit(contender, 0), pool.submit(contender, 1)
        assert sorted([a.result(15), b.result(15)]) == ["40P01", "committed"]
    records = [r for r in caplog.records if r.name == "fides.reliability"]
    assert len(records) == 1
    assert records[0].fields["safe_database_category"] == "deadlock"
    assert records[0].fields["commit_outcome"] == "rolled_back"
