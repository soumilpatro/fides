import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.notification_event import NotificationEvent
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from .helpers import assert_effects, operation, snapshot


@pytest.mark.parametrize(
    "action, model, hook",
    [
        ("create", Commitment, "before_insert"),
        ("create", CommitmentTermsVersion, "before_insert"),
        ("report", Repayment, "before_insert"),
        ("report", LedgerEvent, "before_insert"),
        ("report", AuditLog, "before_insert"),
        ("report", NotificationEvent, "before_insert"),
        ("report", IdempotencyKey, "before_insert"),
        ("verify", RepaymentVerification, "before_insert"),
        ("verify", Commitment, "before_update"),
        ("extension-accept", CommitmentTermsVersion, "before_insert"),
    ],
)
def test_effect_failure_rolls_back_complete_set_and_key_is_reusable(b10, action, model, hook):
    call = operation(b10, action)
    before = snapshot(b10)

    def fail(*args):
        raise SQLAlchemyError("private effect failure")

    event.listen(model, hook, fail)
    try:
        response = call()
        assert response.status_code == 503 and "private" not in response.text
        assert snapshot(b10) == before
    finally:
        event.remove(model, hook, fail)
    assert call().status_code in (200, 201)
    assert_effects(before, snapshot(b10), action)
