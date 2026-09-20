from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.user import User


@pytest.mark.parametrize("actor", ["A", "B"])
@pytest.mark.parametrize("state", ["ACCEPTED", "BLOCKED", "REMOVED"])
def test_connection_independence(timeline, actor, state):
    with timeline.api.factory.begin() as db:
        db.get(Connection, UUID(timeline.connection)).status = state
    assert timeline.timeline(actor).status_code == 200


@pytest.mark.parametrize("actor", ["A", "B"])
def test_closed_readable(timeline, actor):
    with timeline.api.factory.begin() as db:
        db.get(Commitment, UUID(timeline.identifier)).status = "CLOSED"
    assert timeline.timeline(actor).status_code == 200


def test_missing_unrelated_same_error(timeline):
    missing = timeline.timeline(identifier=uuid4())
    unrelated = timeline.timeline("C")
    assert missing.status_code == unrelated.status_code == 404
    assert (
        missing.json()
        == unrelated.json()
        == {"error": {"code": "NOT_FOUND", "message": "Unavailable resource."}}
    )


def test_connected_unrelated(timeline):
    connection = timeline.call("POST", json={"phone": timeline.phones["C"]}).json()["id"]
    assert timeline.call("POST", f"/{connection}/accept", actor="C").status_code == 200
    assert timeline.timeline("C").status_code == 404


@pytest.mark.parametrize("actor", ["A", "B"])
def test_deactivation_preserves_counterparty_history(timeline, actor):
    before = timeline.timeline().json()
    with timeline.api.factory.begin() as db:
        db.get(User, timeline.users[actor]).status = "DEACTIVATED"
    assert timeline.timeline(actor).status_code == 403
    assert timeline.timeline("B" if actor == "A" else "A").json() == before


def test_cursor_is_not_authorization(timeline):
    cursor = timeline.timeline(params={"limit": 1}).json()["next_cursor"]
    assert timeline.timeline("C", params={"cursor": cursor}).status_code == 404
    with timeline.api.factory.begin() as db:
        db.get(User, timeline.users["A"]).status = "DEACTIVATED"
    assert timeline.timeline(params={"cursor": cursor}).status_code == 403
