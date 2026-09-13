import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .test_lifecycle import create

MODELS = (Commitment, CommitmentTermsVersion, LedgerEvent, AuditLog, IdempotencyKey)


@pytest.mark.parametrize("action", ["create", "confirm", "reject", "cancel"])
@pytest.mark.parametrize("failed", MODELS)
def test_each_effect_rolls_back(ctx, action, failed):
    # Terms are only an effect of create; on lifecycle writes test Commitment instead.
    target = Commitment if action != "create" and failed is CommitmentTermsVersion else failed
    row = None if action == "create" else create(ctx)

    def snapshot():
        with ctx.api.factory() as db:
            return {
                m.__name__: list(db.execute(select(m.__table__).order_by(m.id))) for m in MODELS
            }

    before = snapshot()
    hook = "before_update" if action != "create" and target is Commitment else "before_insert"

    def fail(*args):
        raise SQLAlchemyError("private SQL secret phone")

    event.listen(target, hook, fail)
    try:
        response = (
            ctx.request("POST", key="failure", json=ctx.body)
            if action == "create"
            else ctx.request(
                "POST",
                "/" + row["id"] + "/" + action,
                key="failure",
                actor="A" if action == "cancel" else "B",
            )
        )
        assert response.status_code == 503
        assert "private" not in response.text
        assert snapshot() == before
    finally:
        event.remove(target, hook, fail)
