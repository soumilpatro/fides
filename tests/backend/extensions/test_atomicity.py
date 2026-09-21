import json

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.extension_request import ExtensionRequest
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .conftest import requested

MODELS = (
    Commitment,
    CommitmentTermsVersion,
    ExtensionRequest,
    LedgerEvent,
    AuditLog,
    IdempotencyKey,
)


def snapshot(env):
    with env.api.factory() as db:
        return {m.__name__: list(db.execute(select(m.__table__).order_by(m.id))) for m in MODELS}


@pytest.mark.parametrize(
    "action,model,hook",
    [
        (
            action,
            model,
            "after_update" if model is ExtensionRequest and action != "create" else "after_insert",
        )
        for action in ("create", "accept", "reject")
        for model in (
            ExtensionRequest,
            CommitmentTermsVersion,
            LedgerEvent,
            AuditLog,
            IdempotencyKey,
        )
        if model is not CommitmentTermsVersion or action == "accept"
    ],
)
def test_atomic_rollback(b10, action, model, hook, caplog):
    identifier = requested(b10) if action != "create" else None
    before = snapshot(b10)

    def fail(*args):
        raise SQLAlchemyError("sensitive-extension-reason-and-bind")

    event.listen(model, hook, fail)
    try:
        response = (
            b10.create(key="failure", reason="sensitive-extension-reason-and-bind")
            if action == "create"
            else b10.decide(identifier, action, key="failure")
        )
        assert response.status_code == 503
        assert snapshot(b10) == before
        assert "sensitive-extension-reason-and-bind" not in response.text + caplog.text
    finally:
        event.remove(model, hook, fail)
    response = (
        b10.create(key="failure")
        if action == "create"
        else b10.decide(identifier, action, key="failure")
    )
    assert response.status_code == (201 if action == "create" else 200)


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_exact_atomic_events(b10, action, caplog):
    before = snapshot(b10)
    identifier = requested(b10, reason="private-only-response")
    assert b10.decide(identifier, action).status_code == 200
    with b10.api.factory() as db:
        rows = list(
            db.scalars(select(LedgerEvent).where(LedgerEvent.event_type.like("EXTENSION_%")))
        )
        assert len(rows) == 2
        for row in rows:
            payload = row.event_payload
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == row.event_type, AuditLog.object_id == identifier
                )
            )
            assert audit is not None and audit.result == "SUCCESS"
            assert audit.object_type == "ExtensionRequest"
            assert set(audit.metadata_) == {"request_id"}
            actor = b10.users["A" if row.event_type == "EXTENSION_REQUESTED" else "B"]
            assert row.actor_user_id == audit.actor_user_id == actor
            assert row.amount_minor is row.currency is row.repayment_id is None
            assert payload["previous_due_date"] == "2026-10-10"
            assert payload["requested_due_date"] == "2026-11-10"
            assert payload["extension_request_id"] == identifier
            reference = (
                "terms_version_id"
                if row.event_type == "EXTENSION_ACCEPTED"
                else "base_terms_version_id"
            )
            assert str(row.terms_version_id) == payload[reference]
            assert row.occurred_at == audit.created_at == b10.api.clock.now
            assert (
                "private-only-response" not in json.dumps([payload, audit.metadata_]) + caplog.text
            )
    after = snapshot(b10)
    assert all(r in after["LedgerEvent"] for r in before["LedgerEvent"])
    assert all(r in after["AuditLog"] for r in before["AuditLog"])


def test_sql_logging_private(b10, caplog):
    engine = b10.api.factory.kw["bind"]
    engine.echo = True
    try:
        identifier = requested(b10, reason="private-extension-log-check")
        assert b10.decide(identifier).status_code == 200
        assert b10.read().status_code == 200
        assert b10.timeline().status_code == 200
    finally:
        engine.echo = False
    assert "private-extension-log-check" not in caplog.text
