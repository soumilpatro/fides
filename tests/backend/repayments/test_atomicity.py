import json
from uuid import UUID

import pytest
from app.models.audit_log import AuditLog
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

MODELS = (Repayment, LedgerEvent, AuditLog, IdempotencyKey)


def snapshot(b7):
    with b7.api.factory() as db:
        return {m.__name__: list(db.execute(select(m.__table__).order_by(m.id))) for m in MODELS}


@pytest.mark.parametrize("failed", MODELS)
def test_full_rollback_after_each_insert(b7, failed, caplog):
    before = snapshot(b7)

    def fail(*args):
        raise SQLAlchemyError("private note database bind")

    event.listen(failed, "after_insert", fail)
    try:
        result = b7.report(key="failure", note="private note database bind")
        assert result.status_code == 503
        assert snapshot(b7) == before
        assert "private note database bind" not in result.text + caplog.text
    finally:
        event.remove(failed, "after_insert", fail)
    assert b7.report(key="failure").status_code == 201


def test_exact_ledger_audit_and_no_free_text(b7, caplog):
    result = b7.report(note="sensitive free text")
    assert result.status_code == 201
    identifier = UUID(result.json()["id"])
    with b7.api.factory() as db:
        row = db.get(Repayment, identifier)
        ledger = db.scalar(select(LedgerEvent).where(LedgerEvent.repayment_id == identifier))
        audit = db.scalar(select(AuditLog).where(AuditLog.object_id == identifier))
        assert ledger.event_type == audit.action == "REPAYMENT_REPORTED"
        assert ledger.commitment_id == row.commitment_id == UUID(b7.identifier)
        assert (
            ledger.actor_user_id == audit.actor_user_id == row.reported_by_user_id == b7.users["A"]
        )
        assert ledger.terms_version_id is not None
        assert ledger.amount_minor == 1000 and ledger.currency == "INR"
        assert ledger.event_payload == {"status": "PENDING_VERIFICATION"}
        assert ledger.occurred_at == row.reported_at == audit.created_at == b7.api.clock.now
        assert audit.object_type == "Repayment" and audit.result == "SUCCESS"
        assert set(audit.metadata_) == {"request_id"}
        assert (
            "sensitive free text"
            not in json.dumps([ledger.event_payload, audit.metadata_]) + caplog.text
        )


def test_sql_logging_redacts_note(b7, caplog):
    engine = b7.api.factory.kw["bind"]
    engine.echo = True
    try:
        assert b7.report(note="secret-note-in-sql-bind").status_code == 201
    finally:
        engine.echo = False
    assert "secret-note-in-sql-bind" not in caplog.text
