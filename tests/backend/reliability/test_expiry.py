from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from app.models.idempotency_key import IdempotencyKey
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .helpers import assert_effects, snapshot


def expire(env):
    result = env.report(parent=env.identifier, key="expiry")
    assert result.status_code == 201
    with env.api.factory.begin() as db:
        row = db.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == env.users["A"], IdempotencyKey.idempotency_key == "expiry"
            )
        )
        row.expires_at = env.api.clock.now
        return row.id, result.json()


def test_expired_result_replacement_and_retention(b10):
    identifier, original = expire(b10)
    before = snapshot(b10)
    response = b10.report(parent=b10.identifier, key="expiry", amount_minor=1200)
    assert response.status_code == 201
    assert response.json()["id"] != original["id"]
    assert (
        b10.report(parent=b10.identifier, key="expiry", amount_minor=1200).json() == response.json()
    )
    with b10.api.factory() as db:
        row = db.get(IdempotencyKey, identifier)
        assert row.response_body == response.json()
        assert row.expires_at - row.created_at == timedelta(days=30)
    assert len(b10.financial.read(parent=b10.identifier).json()) == 2
    assert_effects(before, snapshot(b10), "report", idempotency_addition=0)


def test_failed_expired_replacement_rolls_back_and_can_retry(b10):
    expire(b10)
    before = snapshot(b10)

    def fail(*args):
        raise SQLAlchemyError("private expired result")

    event.listen(IdempotencyKey, "before_update", fail)
    try:
        result = b10.report(parent=b10.identifier, key="expiry", amount_minor=1200)
        assert result.status_code == 503
        assert snapshot(b10) == before
    finally:
        event.remove(IdempotencyKey, "before_update", fail)
    assert b10.report(parent=b10.identifier, key="expiry", amount_minor=1200).status_code == 201
    assert len(b10.financial.read(parent=b10.identifier).json()) == 2


def test_concurrent_expiry_reuse_is_serialized(b10):
    expire(b10)
    before = snapshot(b10)
    entered, release = Event(), Event()

    def hold(*args):
        entered.set()
        assert release.wait(15)

    def call():
        return b10.report(parent=b10.identifier, key="expiry", amount_minor=1200)

    event.listen(IdempotencyKey, "before_update", hold)
    try:
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(call)
            try:
                assert entered.wait(10)
                loser = call()
                assert loser.status_code == 409
                assert loser.json()["error"]["code"] == "CONFLICT"
            finally:
                release.set()
            winner = first.result(20)
        assert winner.status_code == 201
        assert call().json() == winner.json()
        assert len(b10.financial.read(parent=b10.identifier).json()) == 2
        assert_effects(before, snapshot(b10), "report", idempotency_addition=0)
    finally:
        release.set()
        event.remove(IdempotencyKey, "before_update", hold)


@pytest.mark.parametrize("delta", [timedelta(microseconds=1), timedelta(days=30)])
def test_unexpired_changed_payload_is_not_replaced(b10, delta):
    identifier, _ = expire(b10)
    with b10.api.factory.begin() as db:
        db.get(IdempotencyKey, identifier).expires_at += delta
    before = snapshot(b10)
    response = b10.report(parent=b10.identifier, key="expiry", amount_minor=1200)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert snapshot(b10) == before
