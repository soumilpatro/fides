import psycopg
import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.mutual_closure_request import MutualClosureRequest
from app.models.notification_event import NotificationEvent
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .conftest import error, requested

MODELS = (
    MutualClosureRequest,
    Commitment,
    LedgerEvent,
    AuditLog,
    NotificationEvent,
    IdempotencyKey,
)


def snapshot(mc):
    with mc.api.factory() as db:
        return {
            model.__name__: sorted(
                [
                    tuple(getattr(row, c.key) for c in model.__mapper__.column_attrs)
                    for row in db.scalars(select(model))
                ],
                key=str,
            )
            for model in MODELS
        }


@pytest.mark.parametrize(
    "action,model",
    [
        (action, model)
        for action in ("create", "accept", "reject", "cancel")
        for model in MODELS
        if not (model is Commitment and action != "accept")
        and not (action == "cancel" and model is NotificationEvent)
    ],
)
def test_effect_failure_rolls_back_everything(mc, action, model):
    identifier = None if action == "create" else requested(mc)
    actor = "A" if action in ("create", "cancel") else "B"
    before = snapshot(mc)

    def fail(*args):
        raise SQLAlchemyError("private note token SQL bind")

    hook = (
        "before_update"
        if model is Commitment or (model is MutualClosureRequest and action != "create")
        else "before_insert"
    )
    event.listen(model, hook, fail)
    try:
        result = (
            mc.create(key="atomic")
            if action == "create"
            else mc.decide(identifier, action, actor=actor, key="atomic")
        )
    finally:
        event.remove(model, hook, fail)
    error(result, "SERVICE_UNAVAILABLE", 503)
    assert "private" not in result.text
    assert snapshot(mc) == before
    retry = (
        mc.create(key="atomic")
        if action == "create"
        else mc.decide(identifier, action, actor=actor, key="atomic")
    )
    assert retry.status_code == (201 if action == "create" else 200)


@pytest.mark.parametrize("action", ["create", "accept", "reject", "cancel"])
@pytest.mark.parametrize("lost_ack", [False, True])
def test_commit_failure_and_lost_ack_recovery(mc, monkeypatch, action, lost_ack):
    identifier = None if action == "create" else requested(mc)
    actor = "A" if action in ("create", "cancel") else "B"

    def call():
        return (
            mc.create(key="commit")
            if action == "create"
            else mc.decide(identifier, action, actor=actor, key="commit")
        )

    before = snapshot(mc)
    dialect = mc.api.factory.kw["bind"].dialect
    original = dialect.do_commit
    attempts = []

    def commit(connection):
        attempts.append(1)
        if lost_ack:
            original(connection)
            raise psycopg.OperationalError("private lost acknowledgement")
        raise psycopg.errors.SerializationFailure("private commit failure")

    monkeypatch.setattr(dialect, "do_commit", commit)
    try:
        result = call()
    finally:
        monkeypatch.setattr(dialect, "do_commit", original)
    error(result, "SERVICE_UNAVAILABLE", 503)
    assert attempts == [1]
    intermediate = snapshot(mc)
    assert (intermediate != before) == lost_ack
    assert call().status_code == (201 if action == "create" else 200)
    after = snapshot(mc)
    if lost_ack:
        assert after == intermediate
    assert call().status_code in (200, 201)
    assert snapshot(mc) == after
