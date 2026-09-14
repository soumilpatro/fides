from uuid import UUID

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.user import User
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

MODELS = (
    Commitment,
    CommitmentTermsVersion,
    CommitmentInstallment,
    LedgerEvent,
    AuditLog,
    IdempotencyKey,
)


def snapshot(b6):
    with b6.api.factory() as db:
        return {
            model.__name__: list(db.execute(select(model.__table__).order_by(model.id)))
            for model in MODELS
        }


@pytest.mark.parametrize("failed", MODELS)
def test_rollback_after_each_effect(b6, failed):
    before = snapshot(b6)

    def fail(*args):
        raise SQLAlchemyError("private database information")

    event.listen(failed, "after_insert", fail)
    try:
        response = b6.request("POST", key="failure", json={**b6.body, "terms": b6.terms})
        assert response.status_code == 503
        assert "private" not in response.text
        assert snapshot(b6) == before
    finally:
        event.remove(failed, "after_insert", fail)
    assert b6.request("POST", key="failure", json={**b6.body, "terms": b6.terms}).status_code == 201


@pytest.mark.parametrize("principal", [1, 2])
def test_tiny_invalid_schedule_rolls_back(b6, principal):
    before = snapshot(b6)
    result = b6.request(
        "POST", json={**b6.body, "principal_amount_minor": principal, "terms": b6.terms}
    )
    assert result.status_code == 422 and result.json()["error"]["code"] == "INVALID_AMOUNT"
    assert snapshot(b6) == before


def test_invalid_borrower_timezone_fails_safely(b6):
    with b6.api.factory.begin() as db:
        db.get(User, b6.users["A"]).timezone = "invalid/zone"
    before = snapshot(b6)
    response = b6.request("POST", json={**b6.body, "terms": b6.terms})
    assert response.status_code == 503
    assert snapshot(b6) == before


def test_persisted_reconciliation_and_proposal_reference(b6):
    response = b6.request(
        "POST", json={**b6.body, "principal_amount_minor": 101, "terms": b6.terms}
    )
    assert response.status_code == 201
    identifier = UUID(response.json()["id"])
    with b6.api.factory() as db:
        terms = db.scalar(
            select(CommitmentTermsVersion).where(CommitmentTermsVersion.commitment_id == identifier)
        )
        installments = list(
            db.scalars(
                select(CommitmentInstallment)
                .where(CommitmentInstallment.commitment_id == identifier)
                .order_by(CommitmentInstallment.sequence_no)
            )
        )
        assert terms.version_no == 1
        assert [r.sequence_no for r in installments] == [1, 2, 3]
        assert [r.principal_amount_minor for r in installments] == [33, 33, 35]
        assert [r.interest_amount_minor for r in installments] == [1, 1, 3]
        assert sum(r.total_due_minor for r in installments) == 106
        assert all(r.terms_version_id == terms.id for r in installments)
        ledger = db.scalar(select(LedgerEvent).where(LedgerEvent.commitment_id == identifier))
        assert ledger.terms_version_id == terms.id and ledger.event_type == "COMMITMENT_PROPOSED"
        assert ledger.amount_minor is None
