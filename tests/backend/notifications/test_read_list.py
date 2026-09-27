import base64
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from app.models.notification_event import NotificationEvent
from sqlalchemy import delete

from .conftest import make, notifications
from .test_atomicity import snapshot


def seed(env, count):
    identifier = make(env)
    original = notifications(env)[identifier]
    with env.api.factory.begin() as db:
        db.execute(delete(NotificationEvent).where(NotificationEvent.id == identifier))
        for _ in range(count):
            db.add(NotificationEvent(**{**original, "id": uuid4()}))
    return sorted(notifications(env), reverse=True)


@pytest.mark.parametrize("count,limit", [(0, 50), (1, 1), (3, 1), (51, 50), (101, 100)])
def test_pages_and_tied_order(inbox, count, limit):
    expected = seed(inbox, count)
    params = {} if limit == 50 else {"limit": limit}
    observed = []
    before = notifications(inbox)
    while True:
        response = inbox.inbox(params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert set(page) == {"items", "next_cursor"}
        assert len(page["items"]) <= limit
        observed.extend(item["id"] for item in page["items"])
        if page["next_cursor"] is None:
            break
        assert len(page["items"]) == limit
        params["cursor"] = page["next_cursor"]
    assert observed == list(map(str, expected))
    assert notifications(inbox) == before


def test_live_pagination(inbox):
    expected = seed(inbox, 3)
    first = inbox.inbox(params={"limit": 1}).json()
    inbox.api.clock.now += timedelta(seconds=1)
    newest = make(inbox)
    rest = inbox.inbox(params={"cursor": first["next_cursor"]}).json()
    assert [i["id"] for i in rest["items"]] == list(map(str, expected[1:]))
    assert inbox.inbox().json()["items"][0]["id"] == str(newest)


@pytest.mark.parametrize("limit", ["0", "101", "-1", "1.0", "1e1", "true", "", "١", "+1"])
def test_invalid_limit(inbox, limit):
    assert inbox.inbox(params={"limit": limit}).status_code == 422


@pytest.mark.parametrize("cursor", ["", "!", "a", "x" * 513])
def test_invalid_cursor(inbox, cursor):
    assert inbox.inbox(params={"cursor": cursor}).status_code == 422


@pytest.mark.parametrize(
    "kind", ["version", "boolean_version", "recipient", "naive", "timestamp", "id", "shape"]
)
def test_cursor_shape(inbox, kind):
    parts = [1, str(inbox.users["B"]), inbox.api.clock.now.isoformat(), str(uuid4())]
    if kind == "version":
        parts[0] = 2
    elif kind == "boolean_version":
        parts[0] = True
    elif kind == "recipient":
        parts[1] = str(inbox.users["A"])
    elif kind == "naive":
        parts[2] = "2026-10-01T00:00:00"
    elif kind == "timestamp":
        parts[2] = "invalid"
    elif kind == "id":
        parts[3] = "invalid"
    else:
        parts = {"cursor": parts}
    cursor = base64.urlsafe_b64encode(json.dumps(parts).encode()).decode()
    assert inbox.inbox(params={"cursor": cursor}).status_code == 422


def test_foreign_cursor(inbox):
    seed(inbox, 2)
    cursor = inbox.inbox(params={"limit": 1}).json()["next_cursor"]
    assert inbox.inbox("A", {"cursor": cursor}).status_code == 422


def test_first_read_only_changes_read_state(inbox):
    identifier = make(inbox)
    before = notifications(inbox)[identifier]
    financial = snapshot(inbox, False)
    inbox.api.clock.now += timedelta(seconds=5)
    first = inbox.mark(identifier)
    assert first.status_code == 200
    after = notifications(inbox)[identifier]
    assert after["status"].value == "READ" and after["read_at"] == inbox.api.clock.now
    assert {k: v for k, v in after.items() if k not in ("status", "read_at")} == {
        k: v for k, v in before.items() if k not in ("status", "read_at")
    }
    inbox.api.clock.now += timedelta(seconds=10)
    assert inbox.mark(identifier).json() == first.json()
    assert notifications(inbox)[identifier] == after
    assert snapshot(inbox, False) == financial


def test_corrupt_lookahead_fails_whole_page(inbox):
    rows = seed(inbox, 2)
    with inbox.api.factory.begin() as db:
        db.get(NotificationEvent, rows[1]).payload = {}
    assert inbox.inbox(params={"limit": 1}).status_code == 503
