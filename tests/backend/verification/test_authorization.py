from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.user import User


@pytest.mark.parametrize("reporter,verifier", [("A", "B"), ("B", "A")])
@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_only_counterparty_decides(b8, reporter, verifier, action):
    identifier = b8.report(actor=reporter).json()["id"]
    assert b8.decide(action, actor=reporter, identifier=identifier).status_code == 403
    response = b8.decide(action, actor=verifier, identifier=identifier)
    assert response.status_code == 200
    assert response.json()["reported_by"]["id"] == str(b8.users[reporter])
    for reader in "AB":
        history = b8.history(actor=reader, identifier=identifier).json()
        assert len(history) == 1
        assert history[0]["decided_by"]["id"] == str(b8.users[verifier])


@pytest.mark.parametrize("kind", ["missing", "unrelated", "connected"])
@pytest.mark.parametrize("action", ["verify", "dispute", "history"])
def test_idor(b8, kind, action):
    if kind == "connected":
        connection = b8.call("POST", json={"phone": b8.phones["C"]}).json()["id"]
        assert b8.call("POST", f"/{connection}/accept", actor="C").status_code == 200
    identifier = str(uuid4()) if kind == "missing" else b8.repayment
    actor = "B" if kind == "missing" else "C"
    response = (
        b8.history(actor=actor, identifier=identifier)
        if action == "history"
        else b8.decide(action, actor=actor, identifier=identifier)
    )
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Unavailable resource."}}


@pytest.mark.parametrize("status", ["BLOCKED", "REMOVED"])
@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_connection_independence(b8, status, action):
    with b8.api.factory.begin() as db:
        db.get(Connection, UUID(b8.connection)).status = status
    assert b8.decide(action).status_code == 200
    assert b8.history().status_code == 200


@pytest.mark.parametrize("actor", ["A", "B"])
@pytest.mark.parametrize("status", ["DEACTIVATED", "ANONYMIZED"])
def test_account_eligibility(b8, actor, status):
    with b8.api.factory.begin() as db:
        db.get(User, b8.users[actor]).status = status
    result = b8.decide()
    assert result.status_code == (403 if actor == "B" else 503)


def test_error_precedence(b8):
    with b8.api.factory.begin() as db:
        db.get(Commitment, UUID(b8.identifier)).status = "CLOSED"
    assert b8.decide(actor="C").status_code == 404
    assert b8.decide(actor="A").status_code == 403
    assert b8.decide().json()["error"]["code"] == "INVALID_STATE"
