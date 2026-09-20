import json
from uuid import UUID

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

MODELS = (Repayment, RepaymentVerification, Commitment, LedgerEvent, AuditLog, IdempotencyKey)


def snapshot(b8):
    with b8.api.factory() as db:
        return {m.__name__: list(db.execute(select(m.__table__).order_by(m.id))) for m in MODELS}


@pytest.mark.parametrize(
    "action,model,hook",
    [
        (a, m, "after_update" if m in (Repayment, Commitment) else "after_insert")
        for a in ("verify", "dispute")
        for m in MODELS
        if a == "verify" or m is not Commitment
    ],
)
def test_rollback_at_every_required_step(b8, action, model, hook, caplog):
    before = snapshot(b8)

    def fail(*args):
        raise SQLAlchemyError("secret decision note and database bind")

    event.listen(model, hook, fail)
    try:
        result = b8.decide(
            action, key="failure", body={"decision_note": "secret decision note and database bind"}
        )
        assert result.status_code == 503
        assert snapshot(b8) == before
        assert "secret decision note and database bind" not in result.text + caplog.text
    finally:
        event.remove(model, hook, fail)
    assert b8.decide(action, key="failure").status_code == 200


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_exact_events_and_no_note_leakage(b8, action, caplog):
    assert b8.decide(action, body={"decision_note": "sensitive decision text"}).status_code == 200
    with b8.api.factory() as db:
        history = db.scalar(
            select(RepaymentVerification).where(
                RepaymentVerification.repayment_id == UUID(b8.repayment)
            )
        )
        name = "REPAYMENT_" + history.decision.value
        ledger = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.repayment_id == UUID(b8.repayment), LedgerEvent.event_type == name
            )
        )
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.object_id == UUID(b8.repayment), AuditLog.action == name
            )
        )
        assert (
            ledger.actor_user_id
            == audit.actor_user_id
            == history.decided_by_user_id
            == b8.users["B"]
        )
        assert ledger.amount_minor == 1000 and ledger.currency == "INR"
        assert ledger.commitment_id == UUID(b8.identifier)
        assert ledger.event_payload["verification_id"] == str(history.id)
        assert ledger.event_payload["status"] == history.decision.value
        assert audit.object_type == "Repayment" and audit.result == "SUCCESS"
        assert ledger.occurred_at == audit.created_at == history.decided_at == b8.api.clock.now
        assert set(audit.metadata_) == {"request_id"}
        if action == "verify":
            assert ledger.terms_version_id is not None
            assert ledger.event_payload["verified_outstanding"] == 9000
            assert ledger.event_payload["commitment_status"] == "PARTIALLY_REPAID"
        else:
            assert ledger.terms_version_id is None
            assert set(ledger.event_payload) == {"verification_id", "status"}
        assert (
            "sensitive decision text"
            not in json.dumps([ledger.event_payload, audit.metadata_]) + caplog.text
        )


def test_sql_bind_logging_redacted(b8, caplog):
    engine = b8.api.factory.kw["bind"]
    engine.echo = True
    try:
        assert b8.decide(body={"decision_note": "never-log-this-note"}).status_code == 200
    finally:
        engine.echo = False
    assert "never-log-this-note" not in caplog.text
