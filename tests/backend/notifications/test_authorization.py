from uuid import UUID, uuid4

import pytest
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.user import User
from sqlalchemy import select

from .conftest import TYPES, make, notifications


@pytest.mark.parametrize("kind", TYPES)
def test_only_recipient_owns_notification(inbox, kind):
    identifier = make(inbox, kind)
    assert inbox.mark(identifier, "B").status_code == 200
    for actor in "AC":
        missing = inbox.mark(uuid4(), actor)
        denied = inbox.mark(identifier, actor)
        assert missing.status_code == denied.status_code == 404
        assert (
            missing.json()
            == denied.json()
            == {"error": {"code": "NOT_FOUND", "message": "Unavailable resource."}}
        )
        assert str(identifier) not in [i["id"] for i in inbox.inbox(actor).json()["items"]]


@pytest.mark.parametrize("kind", ["inactive", "revoked"])
@pytest.mark.parametrize("action", ["list", "read"])
def test_current_auth_required(inbox, kind, action):
    identifier = make(inbox)
    with inbox.api.factory.begin() as db:
        if kind == "inactive":
            db.get(User, inbox.users["B"]).status = "DEACTIVATED"
        else:
            for row in db.scalars(
                select(AuthSession).where(AuthSession.user_id == inbox.users["B"])
            ):
                row.revoked_at = inbox.api.clock.now
                row.revocation_reason = "LOGOUT"
    response = inbox.inbox() if action == "list" else inbox.mark(identifier)
    assert response.status_code == (403 if kind == "inactive" else 401)
    assert notifications(inbox)[identifier]["read_at"] is None


@pytest.mark.parametrize("state", ["BLOCKED", "REMOVED"])
@pytest.mark.parametrize(
    "kind",
    [
        "REPAYMENT_REPORTED",
        "REPAYMENT_VERIFIED",
        "REPAYMENT_DISPUTED",
        "EXTENSION_REQUESTED",
        "EXTENSION_ACCEPTED",
        "EXTENSION_REJECTED",
    ],
)
def test_connection_state_independence(inbox, state, kind):
    with inbox.api.factory.begin() as db:
        db.get(Connection, UUID(inbox.connection)).status = state
    identifier = make(inbox, kind)
    assert inbox.inbox().status_code == 200
    assert inbox.mark(identifier).status_code == 200


def test_valid_rejection_not_blocked_by_inactive_recipient(inbox):
    extension = inbox.create(actor="A").json()["id"]
    with inbox.api.factory.begin() as db:
        db.get(Commitment, UUID(inbox.identifier)).status = "CLOSED"
        db.get(User, inbox.users["A"]).status = "DEACTIVATED"
    before = notifications(inbox)
    assert inbox.decide(extension, "reject", actor="B").status_code == 200
    row = notifications(inbox)[next(iter(notifications(inbox).keys() - before.keys()))]
    assert row["user_id"] == inbox.users["A"] and row["type"] == "EXTENSION_REJECTED"
    assert inbox.inbox("A").status_code == 403
    assert inbox.mark(row["id"], "A").status_code == 403
    with inbox.api.factory() as db:
        assert db.get(User, inbox.users["A"]).status.value == "DEACTIVATED"


def test_deactivated_actor_name_projection(inbox):
    identifier = make(inbox)
    with inbox.api.factory.begin() as db:
        db.get(User, inbox.users["A"]).status = "DEACTIVATED"
        db.get(User, inbox.users["A"]).display_name = "Retained actor"
    assert inbox.mark(identifier).json()["actor"]["display_name"] == "Retained actor"
