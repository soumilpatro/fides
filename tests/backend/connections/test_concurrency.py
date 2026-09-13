from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from app.models.connection import Connection
from sqlalchemy import or_, select

from .test_lifecycle import create


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("reconnect", [False, True])
def test_pair_races(peers, reverse, reconnect):
    original = create(peers) if reconnect else None
    if original:
        assert peers.call("DELETE", "/" + original["id"]).status_code == 200
    barrier = Barrier(2)

    def worker(index):
        actor, target = ("B", "A") if reverse and index else ("A", "B")
        barrier.wait(timeout=10)
        return peers.call("POST", actor=actor, json={"phone": peers.phones[target]})

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(worker, range(2)))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert next(r for r in responses if r.status_code == 409).json()["error"]["code"] == "CONFLICT"
    winner = next(r.json() for r in responses if r.status_code == 201)
    with peers.api.factory() as db:
        rows = list(
            db.scalars(
                select(Connection).where(
                    or_(
                        Connection.requester_user_id == peers.users["A"],
                        Connection.recipient_user_id == peers.users["A"],
                    )
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].id == UUID(winner["id"])
        assert str(rows[0].requester_user_id) == winner["requester"]["id"]
        assert str(rows[0].recipient_user_id) == winner["recipient"]["id"]
        if original:
            assert winner["id"] == original["id"]
            assert winner["created_at"] == original["created_at"]


@pytest.mark.parametrize("second", ["accept", "reject"])
def test_competing_pending_transitions_recheck_state(peers, second):
    row = create(peers)
    barrier = Barrier(2)

    def worker(action):
        barrier.wait(timeout=10)
        return peers.call("POST", "/" + row["id"] + "/" + action, actor="B")

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(worker, ["accept", second]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["error"]["code"] == "INVALID_STATE"


def test_state_changed_while_waiting_on_row_lock(peers):
    from threading import Event

    from sqlalchemy import event

    row = create(peers)
    reached = Event()
    engine = peers.api.factory.kw["bind"]

    def observe(connection, cursor, statement, parameters, context, executemany):
        if "FROM connections" in statement and "FOR UPDATE" in statement:
            reached.set()

    with peers.api.factory.begin() as writer:
        locked = writer.scalar(
            select(Connection).where(Connection.id == UUID(row["id"])).with_for_update()
        )
        event.listen(engine, "before_cursor_execute", observe)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(peers.call, "POST", "/" + row["id"] + "/accept", actor="B")
            try:
                assert reached.wait(10)
                locked.status = "BLOCKED"
                writer.commit()
                response = future.result(timeout=15)
            finally:
                writer.rollback()
                event.remove(engine, "before_cursor_execute", observe)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"
