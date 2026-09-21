from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.enums import CommitmentStatus
from app.models.user import User

from .conftest import requested


@pytest.mark.parametrize("requester,decider", [("A", "B"), ("B", "A")])
@pytest.mark.parametrize("action", ["accept", "reject"])
def test_roles(b10, requester, decider, action):
    identifier = requested(b10, actor=requester)
    assert b10.decide(identifier, action, actor=requester).status_code == 403
    assert b10.decide(identifier, action, actor=decider).status_code == 200
    for actor in "AB":
        assert b10.read(actor).status_code == 200


@pytest.mark.parametrize("action", ["create", "read", "accept", "reject"])
def test_missing_unrelated(b10, action):
    identifier = requested(b10)
    if action in ("create", "read"):
        fn = getattr(b10, action)
        missing, unrelated = fn(parent=uuid4()), fn(actor="C")
    else:
        missing, unrelated = b10.decide(uuid4(), action), b10.decide(identifier, action, actor="C")
    assert missing.status_code == unrelated.status_code == 404
    assert (
        missing.json()
        == unrelated.json()
        == {"error": {"code": "NOT_FOUND", "message": "Unavailable resource."}}
    )


@pytest.mark.parametrize("state", ["BLOCKED", "REMOVED"])
@pytest.mark.parametrize("action", ["accept", "reject"])
def test_connection_independence(b10, state, action):
    with b10.api.factory.begin() as db:
        db.get(Connection, UUID(b10.connection)).status = state
    identifier = requested(b10)
    assert b10.decide(identifier, action).status_code == 200
    assert b10.read().status_code == 200


@pytest.mark.parametrize("state", list(CommitmentStatus))
def test_parent_states(b10, state):
    identifier = requested(b10)
    with b10.api.factory.begin() as db:
        db.get(Commitment, UUID(b10.identifier)).status = state
    result = b10.decide(identifier)
    assert result.status_code == (200 if state.value in ("ACTIVE", "PARTIALLY_REPAID") else 409)
    if result.status_code == 409:
        assert result.json()["error"]["code"] == "INVALID_STATE"
        assert b10.decide(identifier, "reject").status_code == 200
        assert b10.create().status_code == 409


@pytest.mark.parametrize("action", ["create", "accept", "reject", "read"])
def test_deactivated_actor(b10, action):
    identifier = requested(b10)
    actor = "A" if action in ("create", "read") else "B"
    with b10.api.factory.begin() as db:
        db.get(User, b10.users[actor]).status = "DEACTIVATED"
    result = (
        getattr(b10, action)() if action in ("create", "read") else b10.decide(identifier, action)
    )
    assert result.status_code == 403


def test_deactivated_requester_does_not_prevent_rejection(b10):
    identifier = requested(b10)
    with b10.api.factory.begin() as db:
        db.get(User, b10.users["A"]).status = "DEACTIVATED"
        db.get(Commitment, UUID(b10.identifier)).status = "CLOSED"
    assert b10.decide(identifier, "reject").status_code == 200
    assert b10.read("B").status_code == 200


@pytest.mark.parametrize("action", ["create", "accept"])
def test_inactive_counterparty_blocks_financial_mutation(b10, action):
    identifier = requested(b10) if action == "accept" else None
    with b10.api.factory.begin() as db:
        db.get(User, b10.users["A" if action == "accept" else "B"]).status = "DEACTIVATED"
    result = b10.decide(identifier) if action == "accept" else b10.create()
    assert result.status_code == 503
