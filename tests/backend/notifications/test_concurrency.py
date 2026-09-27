from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.notification_event import NotificationEvent
from app.models.user import User
from sqlalchemy import event, select

from .conftest import make, notifications, prepare


def race(*actions):
    barrier = Barrier(len(actions))

    def run(action):
        barrier.wait(timeout=10)
        return action()

    with ThreadPoolExecutor(len(actions)) as pool:
        futures = [pool.submit(run, a) for a in actions]
        return [f.result(timeout=25) for f in futures]


def test_concurrent_first_read(inbox):
    identifier = make(inbox)
    results = race(lambda: inbox.mark(identifier), lambda: inbox.mark(identifier))
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    assert results[0].json()["read_at"] is not None
    assert inbox.mark(identifier).json() == results[0].json()


def test_list_read_race(inbox):
    identifier = make(inbox)
    listing, reading = race(inbox.inbox, lambda: inbox.mark(identifier))
    assert listing.status_code == reading.status_code == 200
    assert listing.json()["items"][0]["read_at"] in (None, reading.json()["read_at"])


@pytest.mark.parametrize(
    "kind",
    ["COMMITMENT_PROPOSED", "REPAYMENT_REPORTED", "REPAYMENT_VERIFIED", "EXTENSION_REJECTED"],
)
def test_inflight_replay_during_insertion(inbox, kind):
    run = prepare(inbox, kind)
    before = notifications(inbox)
    entered, release = Event(), Event()

    def hold(*args):
        entered.set()
        assert release.wait(20)

    event.listen(NotificationEvent, "before_insert", hold)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(run, key="inflight-notification")
            try:
                assert entered.wait(10)
                conflict = run(key="inflight-notification")
                assert conflict.status_code == 409, conflict.text
                assert conflict.json()["error"]["code"] == "CONFLICT"
            finally:
                release.set()
            original = future.result(timeout=25)
        assert original.status_code in (200, 201), original.text
        assert run(key="inflight-notification").json() == original.json()
        assert len(notifications(inbox)) == len(before) + 1
    finally:
        release.set()
        event.remove(NotificationEvent, "before_insert", hold)


def test_deactivation_and_valid_rejection(inbox):
    extension = inbox.create(actor="A").json()["id"]
    with inbox.api.factory.begin() as db:
        db.get(Commitment, UUID(inbox.identifier)).status = "CLOSED"
        # Close the fixture's other active commitments so actual deactivation is eligible.
        for parent in db.scalars(
            select(Commitment).where(
                (Commitment.borrower_user_id == inbox.users["A"])
                | (Commitment.lender_user_id == inbox.users["A"])
            )
        ):
            parent.status = "CLOSED"
    before = notifications(inbox)
    results = race(
        lambda: inbox.decide(extension, "reject", actor="B"),
        lambda: inbox.api.client.post("/api/v1/me/deactivate", headers=inbox.headers["A"]),
    )
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    added = notifications(inbox).keys() - before.keys()
    assert len(added) == 1
    assert notifications(inbox)[added.pop()]["user_id"] == inbox.users["A"]
    assert inbox.inbox("A").status_code in (401, 403)


def test_independent_commitments(inbox):
    other = inbox.commitment(terms={"due_date": "2026-10-10", "interest_type": "NONE"})
    before = notifications(inbox)
    results = race(inbox.create, lambda: inbox.create(parent=other))
    assert [r.status_code for r in results] == [201, 201]
    assert len(notifications(inbox)) == len(before) + 2


@pytest.mark.parametrize("model", [Commitment, Connection])
@pytest.mark.parametrize("operation", ["list", "read"])
def test_no_financial_parent_or_connection_lock(inbox, model, operation):
    identifier = make(inbox, "REPAYMENT_REPORTED")
    target = UUID(inbox.identifier if model is Commitment else inbox.connection)
    with inbox.api.factory.begin() as writer:
        writer.scalar(select(model).where(model.id == target).with_for_update())
        with ThreadPoolExecutor(1) as pool:
            response = pool.submit(
                inbox.inbox if operation == "list" else lambda: inbox.mark(identifier)
            ).result(timeout=10)
        assert response.status_code == 200, response.text


def test_revalidate_after_wait(inbox):
    identifier = make(inbox)
    with ThreadPoolExecutor(1) as pool:
        with inbox.api.factory.begin() as writer:
            user = writer.scalar(select(User).where(User.id == inbox.users["B"]).with_for_update())
            future = pool.submit(inbox.mark, identifier)
            user.status = "DEACTIVATED"
        assert future.result(timeout=20).status_code == 403
    assert notifications(inbox)[identifier]["read_at"] is None
