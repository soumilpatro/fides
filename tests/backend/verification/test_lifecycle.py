from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.enums import CommitmentStatus, RepaymentStatus
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from app.models.user import User

from .conftest import seed


@pytest.mark.parametrize("state", list(RepaymentStatus))
@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_repayment_matrix(b8, state, action):
    identifier = seed(b8, 500, state.value)
    response = b8.decide(action, identifier=identifier)
    if state == RepaymentStatus.PENDING_VERIFICATION:
        assert response.status_code == 200
    else:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == (
            "ALREADY_VERIFIED" if state == RepaymentStatus.VERIFIED else "INVALID_STATE"
        )


@pytest.mark.parametrize("state", list(CommitmentStatus))
@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_parent_matrix(b8, state, action):
    with b8.api.factory.begin() as db:
        db.get(Commitment, UUID(b8.identifier)).status = state
    response = b8.decide(action)
    assert response.status_code == (200 if state.value in ("ACTIVE", "PARTIALLY_REPAID") else 409)
    if response.status_code == 409:
        assert response.json()["error"]["code"] == "INVALID_STATE"


@pytest.mark.parametrize("action", ["verify", "dispute"])
@pytest.mark.parametrize("amount", [1000, 10000])
def test_lifecycle_and_original_report_immutability(b8, action, amount):
    with b8.api.factory.begin() as db:
        row = db.get(Repayment, UUID(b8.repayment))
        row.amount_minor = amount
        before = {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "status"}
        parent = db.get(Commitment, UUID(b8.identifier))
        updated = parent.updated_at
    response = b8.decide(action)
    assert response.status_code == 200
    with b8.api.factory() as db:
        row = db.get(Repayment, UUID(b8.repayment))
        assert {
            c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "status"
        } == before
        parent = db.get(Commitment, UUID(b8.identifier))
        assert parent.status.value == (
            "ACTIVE"
            if action == "dispute"
            else "FULLY_REPAID"
            if amount == 10000
            else "PARTIALLY_REPAID"
        )
        assert parent.closed_at is None
        assert (
            (parent.updated_at > updated) if action == "verify" else (parent.updated_at == updated)
        )


def test_partial_then_full_and_no_automatic_closure(b8):
    assert b8.decide().status_code == 200
    with b8.api.factory() as db:
        changed = db.get(Commitment, UUID(b8.identifier)).updated_at
    second = b8.report(amount_minor=1000).json()["id"]
    assert b8.decide(identifier=second).status_code == 200
    with b8.api.factory() as db:
        assert db.get(Commitment, UUID(b8.identifier)).updated_at == changed
    last = b8.report(amount_minor=8000).json()["id"]
    assert b8.decide(identifier=last).status_code == 200
    assert b8.decide(identifier=last).json()["error"]["code"] == "ALREADY_VERIFIED"
    assert (
        b8.api.client.post("/api/v1/me/deactivate", headers=b8.headers["A"]).json()["error"]["code"]
        == "ACCOUNT_HAS_UNRESOLVED_COMMITMENTS"
    )


@pytest.mark.parametrize(
    "first,second",
    [("verify", "verify"), ("verify", "dispute"), ("dispute", "verify"), ("dispute", "dispute")],
)
def test_one_decision_no_reopening(b8, first, second):
    assert b8.decide(first).status_code == 200
    assert b8.decide(second).status_code == 409
    assert len(b8.history().json()) == 1


def test_history_empty_and_current_display_name(b8):
    assert b8.history().json() == []
    assert b8.decide(body={"decision_note": "  confirmed  "}).status_code == 200
    with b8.api.factory.begin() as db:
        db.get(User, b8.users["B"]).display_name = "New name"
    row = b8.history().json()[0]
    assert row["decided_by"]["display_name"] == "New name"
    assert row["decision_note"] == "confirmed"


@pytest.mark.parametrize(
    "kind",
    [
        "pending_history",
        "missing_history",
        "duplicate_history",
        "wrong_decision",
        "wrong_actor",
        "wrong_reporter",
        "wrong_currency",
    ],
)
@pytest.mark.parametrize("operation", ["verify", "dispute", "history"])
def test_inconsistent_history_fails_safely(b8, kind, operation):
    with b8.api.factory.begin() as db:
        row = db.get(Repayment, UUID(b8.repayment))
        if kind == "wrong_reporter":
            row.reported_by_user_id = b8.users["C"]
        elif kind == "wrong_currency":
            row.currency = "USD"
        elif kind == "missing_history":
            row.status = "VERIFIED"
        else:
            if kind != "pending_history":
                row.status = "VERIFIED"
            for _ in range(2 if kind == "duplicate_history" else 1):
                db.add(
                    RepaymentVerification(
                        repayment_id=row.id,
                        decided_by_user_id=b8.users["C"]
                        if kind == "wrong_actor"
                        else b8.users["B"],
                        decision="DISPUTED" if kind == "wrong_decision" else "VERIFIED",
                        decided_at=b8.api.clock.now,
                    )
                )
    response = b8.history() if operation == "history" else b8.decide(operation)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_no_history_mutation_routes(b8):
    assert b8.decide().status_code == 200
    before = b8.history().json()
    for method in ("PATCH", "PUT", "DELETE"):
        response = b8.api.client.request(
            method,
            f"/api/v1/repayments/{b8.repayment}/verification-history",
            headers=b8.headers["B"],
            json={},
        )
        assert response.status_code == 405
    assert b8.history().json() == before
