import base64
import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.models.ledger_event import LedgerEvent
from sqlalchemy import delete, select


def seed(env, count):
    with env.api.factory.begin() as db:
        db.execute(delete(LedgerEvent).where(LedgerEvent.commitment_id == UUID(env.identifier)))
        for i in range(count):
            db.add(
                LedgerEvent(
                    id=UUID(int=1000 + i),
                    commitment_id=UUID(env.identifier),
                    actor_user_id=env.users["B"],
                    event_type="COMMITMENT_CONFIRMED",
                    event_payload={"status": "ACTIVE"},
                    occurred_at=env.api.clock.now + timedelta(seconds=i // 3),
                    created_at=env.api.clock.now - timedelta(seconds=i),
                )
            )


@pytest.mark.parametrize("count,limit", [(0, None), (1, 1), (3, 1), (51, None), (101, 100), (7, 2)])
def test_pages_order_boundaries(timeline, count, limit):
    seed(timeline, count)
    params = {} if limit is None else {"limit": limit}
    seen = []
    while True:
        response = timeline.timeline(params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["items"]) == min(limit or 50, count - len(seen))
        seen.extend(x["id"] for x in page["items"])
        if page["next_cursor"] is None:
            break
        params["cursor"] = page["next_cursor"]
    assert seen == [str(UUID(int=1000 + i)) for i in range(count)]


@pytest.mark.parametrize("value", ["0", "-1", "101", "1.0", "1e1", "true", "", "abc", "１"])
def test_invalid_limits(timeline, value):
    result = timeline.timeline(params={"limit": value})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("value", ["", "!", "a", "e30", "W10", "bnVsbA", "x" * 513])
def test_malformed_cursor(timeline, value):
    assert timeline.timeline(params={"cursor": value}).status_code == 422


@pytest.mark.parametrize(
    "index,value",
    [(0, True), (0, 2), (1, str(uuid4())), (2, "2026-09-11"), (2, "bad"), (3, "bad"), (3, 42)],
)
def test_cursor_fields(timeline, index, value):
    data = [1, timeline.identifier, timeline.api.clock.now.isoformat(), str(uuid4())]
    data[index] = value
    cursor = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    assert timeline.timeline(params={"cursor": cursor}).status_code == 422


def test_wrong_parent_cursor(timeline):
    cursor = timeline.timeline(params={"limit": 1}).json()["next_cursor"]
    parent = timeline.commitment()
    assert timeline.timeline(identifier=parent, params={"cursor": cursor}).status_code == 422


@pytest.mark.parametrize("timestamp", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"])
def test_cursor_utc_overflow_is_validation_error(timeline, timestamp):
    data = [1, timeline.identifier, timestamp, str(uuid4())]
    cursor = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    assert timeline.timeline(params={"cursor": cursor}).status_code == 422


def test_scalar_duplicates_follow_existing_fastapi_convention(timeline):
    result = timeline.timeline(params=[("limit", "2"), ("limit", "1")])
    assert result.status_code == 200 and len(result.json()["items"]) == 1
    cursor = result.json()["next_cursor"]
    assert timeline.timeline(params=[("cursor", "bad"), ("cursor", cursor)]).status_code == 200


def test_no_filter_or_offset_semantics(timeline):
    before = timeline.timeline().json()
    assert timeline.timeline(params={"offset": 1, "event_type": "NONE"}).json() == before


def test_live_page_new_later_event(timeline):
    seed(timeline, 3)
    first = timeline.timeline(params={"limit": 2}).json()
    with timeline.api.factory.begin() as db:
        db.add(
            LedgerEvent(
                id=UUID(int=9999),
                commitment_id=UUID(timeline.identifier),
                actor_user_id=timeline.users["B"],
                event_type="COMMITMENT_CONFIRMED",
                event_payload={"status": "ACTIVE"},
                occurred_at=timeline.api.clock.now + timedelta(days=1),
            )
        )
    result = timeline.timeline(params={"cursor": first["next_cursor"]}).json()
    assert [r["id"] for r in result["items"]] == [str(UUID(int=1002)), str(UUID(int=9999))]


def test_bad_lookahead_fails_whole_page(timeline):
    seed(timeline, 3)
    with timeline.api.factory.begin() as db:
        row = db.scalar(select(LedgerEvent).where(LedgerEvent.id == UUID(int=1001)))
        row.event_type = "UNKNOWN"
    result = timeline.timeline(params={"limit": 1})
    assert result.status_code == 503 and "items" not in result.json()
