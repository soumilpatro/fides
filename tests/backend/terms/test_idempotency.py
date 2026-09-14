import hashlib

import pytest
from app.idempotency import canonical
from app.models.idempotency_key import IdempotencyKey
from app.models.user import User
from sqlalchemy import select


@pytest.mark.parametrize(
    "terms",
    [{"interest_type": "NONE"}, {"interest_type": "SIMPLE_FIXED", "interest_rate_bps": 500}],
)
def test_normalized_replay(b6, terms):
    first = b6.request("POST", key="same", json={**b6.body, "terms": terms})
    explicit = {
        "due_date": None,
        "installment_dates": None,
        "grace_period_days": 0,
        "interest_rate_bps": None,
        **terms,
    }
    replay = b6.request("POST", key="same", json={**b6.body, "terms": explicit})
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()


@pytest.mark.parametrize(
    "change",
    [
        {"due_date": "2027-01-01", "installment_dates": None},
        {"interest_rate_bps": 501},
        {"installment_dates": ["2026-10-10", "2026-12-11"]},
        {"grace_period_days": 1},
    ],
)
def test_changed_terms_conflict(b6, change):
    first = b6.request("POST", key="same", json={**b6.body, "terms": b6.terms})
    assert first.status_code == 201
    second = b6.request("POST", key="same", json={**b6.body, "terms": {**b6.terms, **change}})
    assert second.status_code == 409 and second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_legacy_hash_and_explicit_snapshot_are_distinct(b6):
    first = b6.request("POST", key="old", json=b6.body)
    assert first.status_code == 201
    expected = hashlib.sha256(
        canonical(
            {
                "actor": str(b6.users["A"]),
                "operation": "create",
                "resource": None,
                "request": b6.body,
            }
        ).encode()
    ).hexdigest()
    with b6.api.factory() as db:
        record = db.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == b6.users["A"], IdempotencyKey.idempotency_key == "old"
            )
        )
        assert record.request_hash == expected
    assert b6.request("POST", key="old", json=b6.body).json() == first.json()
    explicit = b6.request("POST", key="old", json={**b6.body, "terms": {"interest_type": "NONE"}})
    assert explicit.status_code == 409


def test_snapshot_not_recomputed_on_replay_and_auth_checked(b6):
    first = b6.request("POST", key="same", json={**b6.body, "terms": b6.terms})
    assert first.status_code == 201
    path = "/" + first.json()["id"] + "/terms"
    original = b6.request("GET", path).json()
    with b6.api.factory.begin() as db:
        db.get(User, b6.users["A"]).timezone = "America/New_York"
    assert (
        b6.request("POST", key="same", json={**b6.body, "terms": b6.terms}).json() == first.json()
    )
    assert b6.request("GET", path).json() == original
    with b6.api.factory.begin() as db:
        db.get(User, b6.users["A"]).status = "DEACTIVATED"
    assert b6.request("POST", key="same", json={**b6.body, "terms": b6.terms}).status_code == 403


def test_failures_not_cached_and_actor_isolation(b6):
    body = {**b6.body, "terms": b6.terms}
    bad = b6.request(
        "POST", key="retry", json={**body, "terms": {**b6.terms, "interest_rate_bps": True}}
    )
    assert bad.status_code == 422
    assert b6.request("POST", key="retry", actor="C", json=body).status_code == 404
    a = b6.request("POST", key="retry", json=body)
    b = b6.request("POST", key="retry", actor="B", json=body)
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
