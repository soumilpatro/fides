from datetime import datetime
from uuid import UUID, uuid4

import pytest
from app.connections import ConnectionService
from app.models.audit_log import AuditLog
from app.models.connection import Connection
from app.models.user import User
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError


def create(peers):
    response = peers.call("POST", json={"phone": peers.phones["B"]})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_detail_list_and_privacy(peers):
    row = create(peers)
    assert set(row) == {
        "id",
        "status",
        "requester",
        "recipient",
        "created_at",
        "updated_at",
    }
    assert row["status"] == "PENDING"
    for role, name in (("requester", "A"), ("recipient", "B")):
        assert row[role] == {"id": str(peers.users[name]), "display_name": "Test user"}
        assert peers.call("GET", "/" + row["id"], actor=name).json() == row
        assert peers.call("GET", actor=name).json() == [row]
    assert peers.call("GET", actor="C").json() == []
    with peers.api.factory() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.object_id == UUID(row["id"])))
        assert audit.action == "CONNECTION_REQUESTED"
        assert audit.actor_user_id == peers.users["A"]
        assert set(audit.metadata_) == {"request_id"}


@pytest.mark.parametrize("state", ["PENDING", "ACCEPTED", "BLOCKED"])
@pytest.mark.parametrize("actor,target", [("A", "B"), ("B", "A")])
def test_duplicate(peers, state, actor, target):
    row = create(peers)
    with peers.api.factory.begin() as db:
        db.get(Connection, UUID(row["id"])).status = state
    response = peers.call("POST", actor=actor, json={"phone": peers.phones[target]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_reconnect_and_list_order(peers):
    original = create(peers)
    assert peers.call("DELETE", "/" + original["id"]).status_code == 200
    second = peers.call("POST", json={"phone": peers.phones["C"]}).json()
    response = peers.call("POST", actor="B", json={"phone": peers.phones["A"]})
    assert response.status_code == 201
    row = response.json()
    assert row["id"] == original["id"]
    assert row["created_at"] == original["created_at"]
    assert datetime.fromisoformat(row["updated_at"]) > datetime.fromisoformat(
        original["updated_at"]
    )
    assert row["requester"]["id"] == str(peers.users["B"])
    assert row["recipient"]["id"] == str(peers.users["A"])
    assert row["status"] == "PENDING"
    assert [r["id"] for r in peers.call("GET").json()] == [row["id"], second["id"]]
    # Direction is authoritative after reconnection.
    assert peers.call("POST", "/" + row["id"] + "/accept", actor="B").status_code == 403
    assert peers.call("POST", "/" + row["id"] + "/accept", actor="A").status_code == 200


@pytest.mark.parametrize("status", ["DEACTIVATED", "ANONYMIZED", "missing", "self"])
def test_target_eligibility(peers, status):
    phone = peers.phones["B"]
    if status == "self":
        phone = peers.phones["A"]
    elif status == "missing":
        phone = "+14155552675"
    else:
        with peers.api.factory.begin() as db:
            db.get(User, peers.users["B"]).status = status
    response = peers.call("POST", json={"phone": phone})
    assert response.status_code == (422 if status == "self" else 404)
    if status != "self":
        assert response.json()["error"] == {
            "code": "NOT_FOUND",
            "message": "Unavailable resource.",
        }


@pytest.mark.parametrize("action", ["accept", "reject", "block", "remove"])
@pytest.mark.parametrize("state", ["PENDING", "ACCEPTED", "BLOCKED", "REMOVED"])
@pytest.mark.parametrize("actor", ["A", "B", "C"])
def test_transition_matrix(peers, action, state, actor):
    row = create(peers)
    identifier = UUID(row["id"])
    with peers.api.factory.begin() as db:
        db.get(Connection, identifier).status = state
    expected, target = 200, "REMOVED"
    if actor == "C":
        expected = 404
    elif action in ("accept", "reject"):
        expected = 403 if actor == "A" else 200 if state == "PENDING" else 409
        target = "ACCEPTED" if action == "accept" else "REMOVED"
    elif state not in ("PENDING", "ACCEPTED"):
        expected = 409
    elif action == "remove" and state == "PENDING" and actor == "B":
        expected = 403
    elif action == "block":
        target = "BLOCKED"
    suffix = "/" + row["id"] + ("" if action == "remove" else "/" + action)
    response = peers.call("DELETE" if action == "remove" else "POST", suffix, actor=actor)
    assert response.status_code == expected, response.text
    with peers.api.factory() as db:
        persisted = db.get(Connection, identifier)
        assert persisted.status.value == (target if expected == 200 else state)
        audits = list(db.scalars(select(AuditLog).where(AuditLog.object_id == identifier)))
        assert len(audits) == (2 if expected == 200 else 1)
        if expected == 200:
            names = {
                "accept": "ACCEPTED",
                "reject": "REJECTED",
                "block": "BLOCKED",
                "remove": "REMOVED",
            }
            assert "CONNECTION_" + names[action] in {a.action for a in audits}
    if expected != 200:
        assert (
            response.json()["error"]["code"]
            == {403: "FORBIDDEN", 404: "NOT_FOUND", 409: "INVALID_STATE"}[expected]
        )


@pytest.mark.parametrize("action", ["accept", "reject", "block", "remove"])
def test_repeated_action(peers, action):
    row = create(peers)
    actor = "B" if action in ("accept", "reject") else "A"
    path = "/" + row["id"] + ("" if action == "remove" else "/" + action)
    method = "DELETE" if action == "remove" else "POST"
    assert peers.call(method, path, actor=actor).status_code == 200
    assert peers.call(method, path, actor=actor).status_code == 409


@pytest.mark.parametrize("action", ["create", "reconnect", "accept", "reject", "block", "remove"])
def test_audit_failure_rolls_back(peers, monkeypatch, action):
    row = None if action == "create" else create(peers)
    if action == "reconnect":
        peers.call("DELETE", "/" + row["id"])

    def fail(*args):
        raise SQLAlchemyError("secret SQL phone token")

    monkeypatch.setattr(ConnectionService, "_audit", fail)
    if action in ("create", "reconnect"):
        response = peers.call("POST", json={"phone": peers.phones["B"]})
    else:
        response = peers.call(
            "DELETE" if action == "remove" else "POST",
            "/" + row["id"] + ("" if action == "remove" else "/" + action),
            actor="B" if action in ("accept", "reject") else "A",
        )
    assert response.status_code == 503
    assert "secret" not in response.text
    with peers.api.factory() as db:
        rows = list(
            db.scalars(select(Connection).where(Connection.requester_user_id == peers.users["A"]))
        )
        if row is None:
            assert rows == []
        else:
            assert len(rows) == 1
            assert rows[0].status.value == ("REMOVED" if action == "reconnect" else "PENDING")


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("GET", ""),
        ("POST", "/accept"),
        ("POST", "/reject"),
        ("POST", "/block"),
        ("DELETE", ""),
    ],
)
def test_missing_and_unrelated_same(peers, method, suffix):
    row = create(peers)
    missing = peers.call(method, "/" + str(uuid4()) + suffix)
    unrelated = peers.call(method, "/" + row["id"] + suffix, actor="C")
    assert missing.status_code == unrelated.status_code == 404
    assert missing.json() == unrelated.json()


@pytest.mark.parametrize("action", ["create", "reconnect", "accept", "reject", "block", "remove"])
def test_database_audit_insert_failure_is_atomic(peers, action):
    from sqlalchemy import event

    row = None if action == "create" else create(peers)
    if action == "reconnect":
        peers.call("DELETE", "/" + row["id"])
    with peers.api.factory() as db:
        before = list(
            db.execute(
                select(Connection.__table__).where(Connection.requester_user_id == peers.users["A"])
            )
        )
        audits = list(
            db.execute(
                select(AuditLog.__table__).where(AuditLog.actor_user_id.in_(peers.users.values()))
            )
        )

    def fail(mapper, connection, target):
        if target.object_type == "Connection":
            raise SQLAlchemyError("audit insertion failed")

    event.listen(AuditLog, "before_insert", fail)
    try:
        if action in ("create", "reconnect"):
            response = peers.call("POST", json={"phone": peers.phones["B"]})
        else:
            response = peers.call(
                "DELETE" if action == "remove" else "POST",
                "/" + row["id"] + ("" if action == "remove" else "/" + action),
                actor="B" if action in ("accept", "reject") else "A",
            )
        assert response.status_code == 503
    finally:
        event.remove(AuditLog, "before_insert", fail)
    with peers.api.factory() as db:
        assert (
            list(
                db.execute(
                    select(Connection.__table__).where(
                        Connection.requester_user_id == peers.users["A"]
                    )
                )
            )
            == before
        )
        assert (
            list(
                db.execute(
                    select(AuditLog.__table__).where(
                        AuditLog.actor_user_id.in_(peers.users.values())
                    )
                )
            )
            == audits
        )
