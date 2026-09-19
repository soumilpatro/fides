from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.connection import Connection
from app.models.enums import CommitmentStatus
from app.models.repayment import Repayment
from app.models.user import User
from sqlalchemy import select

from .conftest import seed


@pytest.mark.parametrize("actor", ["A", "B"])
def test_either_participant_reports_and_reads(b7, actor):
    result = b7.report(actor=actor)
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["reported_by"]["id"] == str(b7.users[actor])
    assert body["status"] == "PENDING_VERIFICATION"
    for reader in "AB":
        assert b7.read(actor=reader).json() == [body]
        assert b7.read(actor=reader, repayment=body["id"]).json() == body
    with b7.api.factory() as db:
        assert db.get(Commitment, UUID(b7.identifier)).status == CommitmentStatus.ACTIVE
        assert db.get(Repayment, UUID(body["id"])).idempotency_key_id is None


@pytest.mark.parametrize("state", list(CommitmentStatus))
def test_every_commitment_state(b7, state):
    with b7.api.factory.begin() as db:
        db.get(Commitment, UUID(b7.identifier)).status = state
    response = b7.report()
    if state.value in ("ACTIVE", "PARTIALLY_REPAID"):
        assert response.status_code == 201
    else:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_STATE"
    with b7.api.factory() as db:
        assert db.get(Commitment, UUID(b7.identifier)).status == state


@pytest.mark.parametrize("connected", [False, True])
@pytest.mark.parametrize("operation", ["report", "list", "detail"])
def test_idor_and_connection_only_access(b7, connected, operation):
    repayment = b7.report().json()["id"]
    if connected:
        row = b7.call("POST", json={"phone": b7.phones["C"]}).json()["id"]
        assert b7.call("POST", f"/{row}/accept", actor="C").status_code == 200
    response = (
        b7.report(actor="C")
        if operation == "report"
        else b7.read(actor="C", repayment=repayment if operation == "detail" else None)
    )
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Unavailable resource."}}


@pytest.mark.parametrize("operation", ["report", "list", "detail"])
def test_missing(b7, operation):
    response = (
        b7.report(parent=str(uuid4()))
        if operation == "report"
        else b7.read(repayment=uuid4())
        if operation == "detail"
        else b7.read(parent=uuid4())
    )
    assert response.status_code == 404


@pytest.mark.parametrize("state", ["BLOCKED", "REMOVED"])
@pytest.mark.parametrize("actor", ["A", "B"])
def test_connection_independence(b7, state, actor):
    with b7.api.factory.begin() as db:
        db.get(Connection, UUID(b7.connection)).status = state
    result = b7.report(actor=actor)
    assert result.status_code == 201
    assert b7.read(actor=actor).json() == [result.json()]
    assert b7.read(actor=actor, repayment=result.json()["id"]).status_code == 200


def test_empty_and_all_status_ordering(b7):
    assert b7.read().json() == []
    ids = [seed(b7, 1, s) for s in ("CANCELLED", "VERIFIED", "DISPUTED", "PENDING_VERIFICATION")]
    latest = seed(
        b7, 1, "PENDING_VERIFICATION", reported_at=b7.api.clock.now + timedelta(seconds=1)
    )
    body = b7.read().json()
    assert [r["id"] for r in body] == [str(latest)] + [str(i) for i in sorted(ids)]
    assert {r["status"] for r in body} == {
        "CANCELLED",
        "VERIFIED",
        "DISPUTED",
        "PENDING_VERIFICATION",
    }
    other = b7.commitment()
    assert b7.read(parent=other).json() == []


def test_prepayment_preserves_installments_and_commitment(b7):
    parent = b7.commitment(terms=b7.terms)
    with b7.api.factory() as db:
        before = list(db.execute(select(CommitmentInstallment.__table__)))
        commitment = list(db.execute(select(Commitment.__table__)))
    response = b7.report(parent=parent, amount_minor=10500)
    assert response.status_code == 201
    with b7.api.factory() as db:
        assert list(db.execute(select(CommitmentInstallment.__table__))) == before
        assert list(db.execute(select(Commitment.__table__))) == commitment
    assert "installment_id" not in Repayment.__table__.columns


@pytest.mark.parametrize("who", ["A", "B"])
def test_deactivated_account(b7, who):
    with b7.api.factory.begin() as db:
        db.get(User, b7.users[who]).status = "DEACTIVATED"
    response = b7.report()
    assert response.status_code == (403 if who == "A" else 404)


def test_precedence_hides_state_and_currency(b7):
    with b7.api.factory.begin() as db:
        db.get(Commitment, UUID(b7.identifier)).status = "CLOSED"
    assert b7.report(actor="C", currency="USD").status_code == 404
    assert b7.report(currency="USD").json()["error"]["code"] == "INVALID_STATE"
    with b7.api.factory.begin() as db:
        db.get(Commitment, UUID(b7.identifier)).status = "ACTIVE"
    assert (
        b7.report(currency="USD", amount_minor=999999).json()["error"]["code"]
        == "CURRENCY_MISMATCH"
    )
