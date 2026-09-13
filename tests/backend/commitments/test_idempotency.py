from datetime import timedelta
from uuid import UUID

import pytest
from app.models.idempotency_key import IdempotencyKey
from app.models.user import User
from sqlalchemy import select

from .test_lifecycle import create


@pytest.mark.parametrize("key", [None, "", "has space", "x" * 129, "bad/", "bad,", "\tbad"])
def test_invalid_key(ctx, key):
    headers = dict(ctx.headers["A"])
    if key is not None:
        headers["Idempotency-Key"] = key
    response = ctx.api.client.post("/api/v1/commitments", json=ctx.body, headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_normalized_replay_and_changed_payload(ctx):
    first = ctx.request("POST", key="same", json={**ctx.body, "description": "  hello  "})
    replay = ctx.request("POST", key="same", json={**ctx.body, "description": "hello"})
    assert replay.status_code == first.status_code == 201
    assert replay.json() == first.json()
    conflict = ctx.request("POST", key="same", json={**ctx.body, "description": "different"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    with ctx.api.factory() as db:
        record = db.scalar(select(IdempotencyKey).where(IdempotencyKey.user_id == ctx.users["A"]))
        assert record.response_body == first.json()
        assert record.expires_at - record.created_at == timedelta(days=30)
        assert len(record.request_hash) == 64


@pytest.mark.parametrize("action", ["confirm", "reject", "cancel"])
def test_lifecycle_lost_response_replay(ctx, action):
    row = create(ctx)
    actor = "A" if action == "cancel" else "B"
    path = "/" + row["id"] + "/" + action
    first = ctx.request("POST", path, actor=actor, key="same")
    replay = ctx.request("POST", path, actor=actor, key="same", json={})
    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert ctx.request("POST", path, actor=actor, key="different").status_code == 409


def test_actor_and_resource_isolation(ctx):
    a = ctx.request("POST", key="same", json=ctx.body)
    b = ctx.request("POST", actor="B", key="same", json=ctx.body)
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    assert a.json()["creator"]["id"] != b.json()["creator"]["id"]
    for response in (a, ctx.request("POST", key="other", json=ctx.body)):
        assert (
            ctx.request(
                "POST", "/" + response.json()["id"] + "/confirm", actor="B", key="same"
            ).status_code
            == 200
        )
    assert ctx.request("POST", "/" + a.json()["id"] + "/cancel", key="same").status_code == 409


def test_failures_not_cached(ctx):
    assert ctx.request("POST", key="retry", json={**ctx.body, "currency": "EUR"}).status_code == 422
    assert ctx.request("POST", key="retry", actor="C", json=ctx.body).status_code == 404
    response = ctx.request("POST", key="retry", json=ctx.body)
    assert response.status_code == 201
    with ctx.api.factory() as db:
        records = list(
            db.scalars(select(IdempotencyKey).where(IdempotencyKey.user_id.in_(ctx.users.values())))
        )
        assert len(records) == 1


def test_replay_revalidates_auth_and_retains_original_body(ctx):
    first = ctx.request("POST", key="same", json=ctx.body)
    assert first.status_code == 201
    ctx.request("POST", "/" + first.json()["id"] + "/confirm", actor="B")
    assert ctx.request("POST", key="same", json=ctx.body).json() == first.json()
    with ctx.api.factory.begin() as db:
        db.get(User, ctx.users["A"]).status = "DEACTIVATED"
    assert ctx.request("POST", key="same", json=ctx.body).status_code == 403


def test_retention_boundary(ctx):
    first = ctx.request("POST", key="same", json=ctx.body).json()
    # Set retention boundary directly; keeping the independently expiring session valid.
    with ctx.api.factory.begin() as db:
        record = db.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.idempotency_key == "same", IdempotencyKey.user_id == ctx.users["A"]
            )
        )
        record.expires_at = ctx.api.clock.now + timedelta(microseconds=1)
    assert ctx.request("POST", key="same", json=ctx.body).json() == first
    ctx.api.clock.now += timedelta(microseconds=1)
    second = ctx.request("POST", key="same", json=ctx.body)
    assert second.status_code == 201 and UUID(second.json()["id"]) != UUID(first["id"])


def test_duplicate_header(ctx):
    headers = list(ctx.headers["A"].items()) + [
        ("Idempotency-Key", "one"),
        ("Idempotency-Key", "two"),
    ]
    response = ctx.api.client.post("/api/v1/commitments", headers=headers, json=ctx.body)
    assert response.status_code == 400


def test_normalization_omitted_null_and_blank(ctx):
    body = dict(ctx.body)
    del body["description"]
    first = ctx.request("POST", key="normalized", json=body)
    for description in (None, "", "   "):
        replay = ctx.request("POST", key="normalized", json={**body, "description": description})
        assert replay.status_code == 201 and replay.json() == first.json()
