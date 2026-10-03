from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from app.models.auth_session import AuthSession
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.mutual_closure_request import MutualClosureRequest
from app.models.repayment_verification import RepaymentVerification
from app.models.user import User
from reliability.test_races import serialized
from sqlalchemy import event

from .conftest import items


def reader_first(env, read, mutate, monkeypatch):
    import app.summary_occurrences as service

    entered, release, waiting = Event(), Event(), Event()
    original = service.utc_now
    engine = env.api.factory.kw["bind"]

    def hold(*args):
        entered.set()
        assert release.wait(15)
        return original(*args)

    def observe(conn, cursor, statement, parameters, context, many):
        if entered.is_set() and "FROM users" in statement and "FOR UPDATE" in statement:
            waiting.set()

    monkeypatch.setattr(service, "utc_now", hold)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(2) as pool:
            reader = pool.submit(read)
            try:
                assert entered.wait(10)
                writer = pool.submit(mutate)
                assert waiting.wait(10) and not writer.done()
            finally:
                release.set()
            return writer.result(20), reader.result(20)
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize("action", ["verify", "extension", "closure"])
@pytest.mark.parametrize("mutation_first", [True, False])
def test_financial_read_serializes(occ, monkeypatch, kind, action, mutation_first):
    occ.configure(due="2026-09-10" if kind == "overdue" else "2026-09-11")
    if action == "verify":
        reported = occ.report(amount_minor=10000)
        assert reported.status_code == 201, reported.text

        def mutate():
            return occ.verify(reported.json()["id"])

        model, hook = RepaymentVerification, "before_insert"
    elif action == "extension":
        proposed = occ.extension()
        assert proposed.status_code == 201

        def mutate():
            return occ.extension(proposed.json()["id"])

        model, hook = CommitmentTermsVersion, "before_insert"
    else:
        proposed = occ.create()
        assert proposed.status_code == 201

        def mutate():
            return occ.decide(proposed.json()["id"])

        model, hook = MutualClosureRequest, "before_update"

    def read():
        return occ.query(kind)

    mutation, response = (
        serialized(occ, mutate, read, model, hook)
        if mutation_first
        else reader_first(occ, read, mutate, monkeypatch)
    )
    assert mutation.status_code == 200, mutation.text
    assert len(items(response)) == (0 if mutation_first else 1)
    assert items(read()) == []


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize("credential_first", [True, False])
def test_session_revocation_race(occ, monkeypatch, kind, credential_first):
    def read():
        return occ.query(kind)

    def logout():
        return occ.api.client.post("/api/v1/auth/logout", headers=occ.headers["A"], json={})

    mutation, response = (
        serialized(occ, logout, read, AuthSession, "before_update")
        if credential_first
        else reader_first(occ, read, logout, monkeypatch)
    )
    assert mutation.status_code == 200
    assert response.status_code == (401 if credential_first else 200)
    assert read().status_code == 401


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize("deactivation_first", [True, False])
def test_real_deactivation_race(occ, monkeypatch, kind, deactivation_first):
    def read():
        return occ.query(kind, "C")

    def deactivate():
        return occ.api.client.post("/api/v1/me/deactivate", headers=occ.headers["C"])

    mutation, response = (
        serialized(occ, deactivate, read, User, "before_update")
        if deactivation_first
        else reader_first(occ, read, deactivate, monkeypatch)
    )
    assert mutation.status_code == 200
    assert response.status_code == (401 if deactivation_first else 200)
    assert read().status_code == 401


def test_evaluation_instant_captured_once(occ, monkeypatch):
    import app.summary_occurrences as service

    original, times = service.utc_now, []

    def track(*args):
        value = original(*args)
        times.append(value)
        return value

    monkeypatch.setattr(service, "utc_now", track)
    assert items(occ.query()) and times == [occ.api.clock.now]
