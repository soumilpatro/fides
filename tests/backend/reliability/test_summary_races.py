from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from app.models.user import User
from sqlalchemy import event

from .helpers import assert_effects, snapshot
from .test_races import serialized


@pytest.mark.parametrize("summary_first", [True, False])
def test_summary_vs_report_is_coherent(b10, monkeypatch, summary_first):
    import app.summary as summary
    from app.models.repayment import Repayment

    def read():
        return b10.api.client.get("/api/v1/summary", headers=b10.headers["A"])

    before = snapshot(b10)
    expected = read().json()

    def report():
        return b10.report(parent=b10.identifier)

    if not summary_first:
        mutation, result = serialized(b10, report, read, Repayment)
    else:
        entered, release, waiting = Event(), Event(), Event()
        original = summary.validate_terms
        engine = b10.api.factory.kw["bind"]

        def hold(*args):
            entered.set()
            assert release.wait(15)
            return original(*args)

        def observe(conn, cursor, sql, parameters, context, many):
            if entered.is_set() and "FROM users" in sql and "FOR UPDATE" in sql:
                waiting.set()

        monkeypatch.setattr(summary, "validate_terms", hold)
        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(2) as pool:
                reader = pool.submit(read)
                try:
                    assert entered.wait(10)
                    writer = pool.submit(report)
                    assert waiting.wait(10) and not writer.done()
                finally:
                    release.set()
                result, mutation = reader.result(20), writer.result(20)
        finally:
            release.set()
            event.remove(engine, "before_cursor_execute", observe)
    assert result.status_code == 200 and mutation.status_code == 201
    # Pending reports consume capacity but cannot change verified summary totals.
    assert result.json() == expected == read().json()
    assert_effects(before, snapshot(b10), "report")


@pytest.mark.parametrize("deactivation_first", [True, False])
def test_summary_vs_real_deactivation_endpoint(peers, monkeypatch, deactivation_first):
    # A genuinely eligible account, rather than direct fixture status corruption.
    import app.summary as summary

    def read():
        return peers.api.client.get("/api/v1/summary", headers=peers.headers["C"])

    def deactivate():
        return peers.api.client.post("/api/v1/me/deactivate", headers=peers.headers["C"])

    if deactivation_first:
        mutation, response = serialized(peers, deactivate, read, User, "before_update")
    else:
        entered, release, waiting = Event(), Event(), Event()
        original = summary.utc_now
        engine = peers.api.factory.kw["bind"]

        def hold(*args):
            entered.set()
            assert release.wait(15)
            return original(*args)

        def observe(conn, cursor, sql, parameters, context, many):
            if entered.is_set() and "FROM users" in sql and "FOR UPDATE" in sql:
                waiting.set()

        monkeypatch.setattr(summary, "utc_now", hold)
        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(2) as pool:
                reader = pool.submit(read)
                try:
                    assert entered.wait(10)
                    writer = pool.submit(deactivate)
                    assert waiting.wait(10) and not writer.done()
                finally:
                    release.set()
                response, mutation = reader.result(20), writer.result(20)
        finally:
            release.set()
            event.remove(engine, "before_cursor_execute", observe)
    assert mutation.status_code == 200
    assert response.status_code == (401 if deactivation_first else 200)
    if not deactivation_first:
        assert all(
            row["borrowed_outstanding_minor"]
            == row["lent_outstanding_minor"]
            == row["net_position_minor"]
            == 0
            for row in response.json()["currencies"]
        )
    assert read().status_code == 401
    with peers.api.factory() as db:
        assert db.get(User, peers.users["C"]).status == "DEACTIVATED"


def test_summary_evaluates_time_once(b10, monkeypatch):
    import app.summary as summary

    original, evaluations = summary.utc_now, []

    def track(*args):
        value = original(*args)
        evaluations.append(value)
        return value

    monkeypatch.setattr(summary, "utc_now", track)
    response = b10.api.client.get("/api/v1/summary", headers=b10.headers["A"])
    assert response.status_code == 200 and evaluations == [b10.api.clock.now]
