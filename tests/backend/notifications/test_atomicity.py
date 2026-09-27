import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.extension_request import ExtensionRequest
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.notification_event import NotificationEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .conftest import TYPES, make, notifications, prepare

MODELS = (
    Commitment,
    CommitmentInstallment,
    CommitmentTermsVersion,
    ExtensionRequest,
    IdempotencyKey,
    LedgerEvent,
    AuditLog,
    NotificationEvent,
    Repayment,
    RepaymentVerification,
)


def snapshot(env, include_notifications=True):
    with env.api.factory() as db:
        return {
            m.__name__: list(db.execute(select(m.__table__).order_by(m.id)))
            for m in MODELS
            if include_notifications or m is not NotificationEvent
        }


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("model", [NotificationEvent, IdempotencyKey])
def test_whole_action_rolls_back(inbox, kind, model, caplog):
    run = prepare(inbox, kind)
    before = snapshot(inbox)

    def fail(*args):
        raise SQLAlchemyError("private-notification-database-detail")

    event.listen(model, "after_insert", fail)
    try:
        response = run(key="rollback")
        assert response.status_code == 503, response.text
        assert snapshot(inbox) == before
        assert "private-notification-database-detail" not in response.text + caplog.text
    finally:
        event.remove(model, "after_insert", fail)
    assert run(key="rollback").status_code in (200, 201)
    assert len(notifications(inbox)) == len(before["NotificationEvent"]) + 1


@pytest.mark.parametrize("kind", TYPES)
def test_completed_domain_replay_unchanged(inbox, kind):
    run = prepare(inbox, kind)
    response = run(key="replay")
    assert response.status_code in (200, 201)
    before = snapshot(inbox)
    replay = run(key="replay")
    assert (replay.status_code, replay.json()) == (response.status_code, response.json())
    assert snapshot(inbox) == before


@pytest.mark.parametrize("kind", ["self_decision", "state", "schema", "overpayment", "unrelated"])
def test_failed_action_no_notification(inbox, kind):
    extension = inbox.create().json()["id"]
    before = snapshot(inbox)
    if kind == "self_decision":
        response = inbox.decide(extension, actor="A")
    elif kind == "state":
        response = inbox.create()
    elif kind == "schema":
        response = inbox.report(parent=inbox.identifier, amount_minor=0)
    elif kind == "overpayment":
        response = inbox.report(parent=inbox.identifier, amount_minor=100000)
    else:
        response = inbox.report(parent=inbox.identifier, actor="C")
    assert response.status_code in (403, 404, 409, 422)
    assert snapshot(inbox) == before


def test_read_persistence_failure_preserves_committed_financial_action(inbox):
    identifier = make(inbox, "REPAYMENT_VERIFIED")
    before = snapshot(inbox)

    def fail(*args):
        raise SQLAlchemyError("private-read-failure")

    event.listen(NotificationEvent, "after_update", fail)
    try:
        response = inbox.mark(identifier)
        assert response.status_code == 503
        assert "private-read-failure" not in response.text
        assert snapshot(inbox) == before
    finally:
        event.remove(NotificationEvent, "after_update", fail)
    assert inbox.mark(identifier).status_code == 200
    assert snapshot(inbox, False) == {k: v for k, v in before.items() if k != "NotificationEvent"}
