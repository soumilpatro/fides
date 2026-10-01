from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy import event, select

from app.models.commitment import Commitment
from app.models.user import User
from .conftest import read


def hold_summary(env, monkeypatch, action, expected_before, expected_after):
    import app.summary as module

    entered, release, writer_lock = Event(), Event(), Event()
    original = module.validate_terms
    engine = env.api.factory.kw["bind"]

    def hold(*args):
        entered.set()
        assert release.wait(15)
        return original(*args)

    def observe(conn, cursor, statement, parameters, context, executemany):
        if entered.is_set() and "FROM users" in statement and "FOR UPDATE" in statement:
            writer_lock.set()

    monkeypatch.setattr(module, "validate_terms", hold)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(2) as pool:
            summary = pool.submit(read, env)
            try:
                assert entered.wait(10)
                writer = pool.submit(action)
                assert writer_lock.wait(10)
                assert not writer.done()
            finally:
                release.set()
            result = summary.result(timeout=20)
            mutation = writer.result(timeout=20)
        assert result.status_code == 200, result.text
        assert mutation.status_code == 200, mutation.text
        assert result.json()["currencies"][0]["borrowed_outstanding_minor"] == expected_before
        assert read(env).json()["currencies"][0]["borrowed_outstanding_minor"] == expected_after
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observe)


def test_summary_serializes_verification(b8, monkeypatch):
    hold_summary(b8, monkeypatch, b8.decide, 10000, 9000)


def test_summary_serializes_extension(b10, monkeypatch):
    extension = b10.create().json()["id"]
    hold_summary(b10, monkeypatch, lambda: b10.decide(extension), 20500, 20500)


@pytest.mark.parametrize("action", ["confirm", "cancel"])
def test_summary_serializes_lifecycle(b7, monkeypatch, action):
    proposed = b7.request("POST", json=b7.body)
    assert proposed.status_code == 201
    actor = "B" if action == "confirm" else "A"
    hold_summary(
        b7,
        monkeypatch,
        lambda: b7.request("POST", f"/{proposed.json()['id']}/{action}", actor=actor),
        10000,
        20000 if action == "confirm" else 10000,
    )


def test_summary_does_not_lock_commitments(b7):
    with b7.api.factory.begin() as writer:
        writer.scalar(
            select(Commitment).where(Commitment.id == UUID(b7.identifier)).with_for_update()
        )
        with ThreadPoolExecutor(1) as pool:
            result = pool.submit(read, b7).result(timeout=10)
        assert result.status_code == 200, result.text


def test_revalidation_after_user_lock_wait(b7):
    entered = Event()
    engine = b7.api.factory.kw["bind"]

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            entered.set()

    with ThreadPoolExecutor(1) as pool:
        with b7.api.factory.begin() as writer:
            user = writer.scalar(select(User).where(User.id == b7.users["A"]).with_for_update())
            event.listen(engine, "before_cursor_execute", observe)
            try:
                future = pool.submit(read, b7)
                assert entered.wait(10)
                assert not future.done()
                user.status = "DEACTIVATED"
            finally:
                event.remove(engine, "before_cursor_execute", observe)
        assert future.result(timeout=20).status_code == 403


@pytest.mark.parametrize("kind", ["verification", "extension"])
def test_summary_waits_for_writer_and_reads_committed_result(b10, monkeypatch, kind):
    import app.summary as module
    from app.models.commitment_terms_version import CommitmentTermsVersion

    if kind == "verification":
        model, event_name = Commitment, "after_update"
        target = UUID(b10.financial.identifier)
        action = b10.financial.decide
        expected = 19500
    else:
        identifier = b10.create().json()["id"]
        model, event_name = CommitmentTermsVersion, "after_insert"
        target = UUID(b10.identifier)

        def action():
            return b10.decide(identifier)

        expected = 20500
    entered, release, reader_lock = Event(), Event(), Event()
    engine = b10.api.factory.kw["bind"]
    selected = {}
    original = module.validate_terms

    def remember(term, parent):
        selected[parent.id] = term.version_no
        return original(term, parent)

    def hold(mapper, connection, row):
        identity = row.id if kind == "verification" else row.commitment_id
        if identity == target:
            entered.set()
            assert release.wait(15)

    def observe(conn, cursor, statement, parameters, context, executemany):
        if entered.is_set() and "FROM users" in statement and "FOR UPDATE" in statement:
            reader_lock.set()

    monkeypatch.setattr(module, "validate_terms", remember)
    event.listen(model, event_name, hold)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(2) as pool:
            writer = pool.submit(action)
            try:
                assert entered.wait(10)
                reader = pool.submit(read, b10)
                assert reader_lock.wait(10)
                assert not reader.done()
            finally:
                release.set()
            mutation = writer.result(timeout=20)
            response = reader.result(timeout=20)
        assert mutation.status_code == response.status_code == 200
        assert response.json()["currencies"][0]["borrowed_outstanding_minor"] == expected
        if kind == "extension":
            assert selected[target] == 2
    finally:
        release.set()
        event.remove(model, event_name, hold)
        event.remove(engine, "before_cursor_execute", observe)
