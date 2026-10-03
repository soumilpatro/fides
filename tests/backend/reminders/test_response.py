from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.api.notification_schemas import NotificationResponse
from app.models.commitment import Commitment
from app.models.notification_event import NotificationEvent
from app.models.repayment import Repayment
from pydantic import ValidationError

from repayments.conftest import seed


@pytest.mark.parametrize(
    "kind,due",
    [("UPCOMING_DUE", "2026-09-14"), ("DUE_TODAY", "2026-09-11"), ("OVERDUE", "2026-09-10")],
)
def test_reminder_projection_and_owned_read(env, kind, due):
    env.configure(due)
    env.job.run(now=env.api.clock.now)
    response = env.inbox("A")
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["type"] == kind
    assert item["actor"] is None
    assert item["commitment_id"] == str(env.parent_id)
    assert item["repayment_id"] is item["extension_request_id"] is None
    assert set(item) == {
        "id",
        "type",
        "actor",
        "commitment_id",
        "repayment_id",
        "extension_request_id",
        "created_at",
        "read_at",
    }
    assert env.mark(item["id"], "C").status_code == 404
    first = env.mark(item["id"], "A")
    assert first.status_code == 200
    assert first.json()["read_at"] is not None
    assert first.json() == env.mark(item["id"], "A").json()


def test_historical_read_after_repayment_and_progression(env):
    env.job.run(now=env.api.clock.now)
    seed(env, 10500, "VERIFIED")
    with env.api.factory.begin() as db:
        report = db.get(Repayment, UUID(env.repayment))
        report.status, report.amount_minor = "VERIFIED", 10500
        db.get(Commitment, env.parent_id).status = "FULLY_REPAID"
    assert env.job.run(now=env.api.clock.now)["created"] == 0
    assert env.inbox("A").status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("terms_version_id", str(uuid4())),
        ("installment_id", str(uuid4())),
        ("scheduled_local_date", "not-date"),
        ("extra", "private"),
    ],
)
def test_invalid_payload_unavailable_without_leak(env, field, value):
    env.job.run(now=env.api.clock.now)
    row = env.rows()[0]
    with env.api.factory.begin() as db:
        stored = db.get(NotificationEvent, row.id)
        stored.payload = {**stored.payload, field: value}
    response = env.inbox("A")
    assert response.status_code == 503
    assert value not in response.text


def test_workflow_actor_preserved_and_preferences_ignored(env):
    env.preference("A", due=False, overdue=False)
    assert env.create(actor="B").status_code == 201
    response = env.inbox("A")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["type"] == "EXTENSION_REQUESTED"
    assert item["actor"]["id"] == str(env.users["B"])


@pytest.mark.parametrize(
    "kind,actor,valid",
    [
        ("UPCOMING_DUE", None, True),
        ("OVERDUE", None, True),
        ("DUE_TODAY", {"id": str(uuid4()), "display_name": "Human"}, False),
        ("COMMITMENT_PROPOSED", None, False),
        ("EXTENSION_ACCEPTED", {"id": str(uuid4()), "display_name": "Human"}, True),
    ],
)
def test_actor_union_enforced(kind, actor, valid):
    body = dict(
        id=uuid4(),
        type=kind,
        actor=actor,
        commitment_id=uuid4(),
        repayment_id=None,
        extension_request_id=None,
        created_at="2026-09-11T12:00:00Z",
        read_at=None,
    )
    if valid:
        NotificationResponse(**body)
    else:
        with pytest.raises(ValidationError):
            NotificationResponse(**body)


def test_mixed_cursor_order(env):
    env.job.run(now=env.api.clock.now)
    env.api.clock.now += timedelta(seconds=1)
    assert env.create(actor="B").status_code == 201
    first = env.inbox("A", {"limit": 1}).json()
    second = env.inbox("A", {"limit": 1, "cursor": first["next_cursor"]}).json()
    assert first["items"][0]["type"] == "EXTENSION_REQUESTED"
    assert second["items"][0]["type"] == "UPCOMING_DUE"
    assert second["next_cursor"] is None
