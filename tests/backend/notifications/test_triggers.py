from uuid import UUID

import pytest
from app.models.ledger_event import LedgerEvent
from app.models.user import User

from .conftest import TYPES, make, notifications, prepare


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("actor", ["A", "B"])
def test_exact_trigger_recipient_storage(inbox, kind, actor):
    identifier = make(inbox, kind, actor)
    row = notifications(inbox)[identifier]
    other = "B" if actor == "A" else "A"
    assert row["user_id"] == inbox.users[other] and row["user_id"] != inbox.users[actor]
    assert row["type"] == kind
    assert set(row["payload"]) == {"source_ledger_event_id"}
    assert row["status"].value == "DELIVERED"
    assert row["read_at"] is row["sent_at"] is row["scheduled_at"] is None
    with inbox.api.factory() as db:
        source = db.get(LedgerEvent, UUID(row["payload"]["source_ledger_event_id"]))
        assert source.event_type == kind and source.actor_user_id == inbox.users[actor]
        assert row["created_at"] == source.occurred_at
        object_type = (
            "Commitment"
            if kind.startswith("COMMITMENT")
            else "Repayment"
            if kind.startswith("REPAYMENT")
            else "ExtensionRequest"
        )
        assert row["object_type"] == object_type
        assert row["object_id"] == (
            source.commitment_id
            if object_type == "Commitment"
            else source.repayment_id
            if object_type == "Repayment"
            else UUID(source.event_payload["extension_request_id"])
        )
    response = inbox.inbox(other)
    assert response.status_code == 200, response.text
    item = next(x for x in response.json()["items"] if x["id"] == str(identifier))
    assert item["actor"]["id"] == str(inbox.users[actor])
    assert item["type"] == kind
    assert item["repayment_id"] == (str(row["object_id"]) if kind.startswith("REPAYMENT") else None)
    assert item["extension_request_id"] == (
        str(row["object_id"]) if kind.startswith("EXTENSION") else None
    )


@pytest.mark.parametrize("kind", TYPES[:4])
def test_reverse_lending_direction(inbox, kind):
    run = prepare(inbox, kind, role="LENDER")
    before = notifications(inbox)
    assert run().status_code in (200, 201)
    row = notifications(inbox)[next(iter(notifications(inbox).keys() - before.keys()))]
    assert row["user_id"] == inbox.users["B"]
    assert inbox.inbox("B").status_code == 200


def test_no_backfill_or_read_trigger(inbox):
    assert notifications(inbox) == {}
    for actor in "ABC":
        assert inbox.inbox(actor).json() == {"items": [], "next_cursor": None}
    for path in (
        f"/api/v1/commitments/{inbox.identifier}/ledger",
        f"/api/v1/commitments/{inbox.identifier}/terms",
        f"/api/v1/commitments/{inbox.identifier}/installments",
        "/api/v1/me",
    ):
        assert inbox.api.client.get(path, headers=inbox.headers["A"]).status_code == 200
    assert notifications(inbox) == {}


def test_historical_action_and_current_name(inbox):
    identifier = make(inbox)
    row = notifications(inbox)[identifier]
    assert inbox.request("POST", f"/{row['object_id']}/confirm", actor="B").status_code == 200
    with inbox.api.factory.begin() as db:
        db.get(User, inbox.users["A"]).display_name = "Current actor"
    response = inbox.inbox()
    assert response.status_code == 200
    item = next(x for x in response.json()["items"] if x["id"] == str(identifier))
    assert (
        item["type"] == "COMMITMENT_PROPOSED" and item["actor"]["display_name"] == "Current actor"
    )
