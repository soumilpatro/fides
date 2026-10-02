import logging

import psycopg
import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from .helpers import OPERATIONS, assert_effects, operation, snapshot


@pytest.mark.parametrize("action", OPERATIONS)
@pytest.mark.parametrize("failure", ["after_flush", "commit", "lost_ack"])
def test_transaction_boundaries_and_recovery(b10, monkeypatch, caplog, action, failure):
    call = operation(b10, action)
    # Fixed correlation is asserted in both the HTTP response and diagnostic.
    for headers in b10.headers.values():
        headers["X-Request-ID"] = "b13-commit-boundary"
    before = snapshot(b10)
    factory = b10.api.factory
    dialect = factory.kw["bind"].dialect
    original = dialect.do_commit
    attempts = []

    def commit(connection):
        attempts.append("commit")
        if failure == "lost_ack":
            original(connection)
            raise psycopg.OperationalError("private commit acknowledgement lost")
        raise psycopg.errors.SerializationFailure("private commit failure")

    def flushed(db, context):
        # Idempotency completion is the LAST explicit flush, after all effects.
        if any(type(row).__name__ == "IdempotencyKey" for row in db.identity_map.values()):
            attempts.append("flushed")
            raise SQLAlchemyError("private bind phone token note")

    with caplog.at_level(logging.WARNING, logger="fides.reliability"):
        if failure == "after_flush":
            event.listen(factory, "after_flush_postexec", flushed)
        else:
            monkeypatch.setattr(dialect, "do_commit", commit)
        try:
            result = call()
        finally:
            if failure == "after_flush":
                event.remove(factory, "after_flush_postexec", flushed)
            else:
                monkeypatch.setattr(dialect, "do_commit", original)
    assert attempts == ["flushed" if failure == "after_flush" else "commit"]
    assert result.status_code == 503, result.text
    assert result.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert result.headers["X-Request-ID"] == "b13-commit-boundary"
    records = [r for r in caplog.records if r.name == "fides.reliability"]
    assert len(records) == 1
    assert records[0].fields["request_id"] == "b13-commit-boundary"
    assert records[0].fields["failure_phase"] == ("body" if failure == "after_flush" else "commit")
    assert (
        records[0].fields["commit_outcome"]
        == {"lost_ack": "uncertain", "commit": "rolled_back", "after_flush": "unknown"}[failure]
    )
    assert "private" not in str(records[0].fields) + result.text
    intermediate = snapshot(b10)
    if failure == "lost_ack":
        assert_effects(before, intermediate, action)
    else:
        assert intermediate == before
    retry = call()
    assert retry.status_code == (201 if action in ("create", "report", "extension-create") else 200)
    after = snapshot(b10)
    assert_effects(before, after, action)
    if failure == "lost_ack":
        assert after == intermediate
    assert call().json() == retry.json()
    assert snapshot(b10) == after
