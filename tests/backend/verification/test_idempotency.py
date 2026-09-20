import hashlib
import json
from datetime import timedelta
from uuid import UUID

import pytest
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.idempotency_key import IdempotencyKey
from app.models.repayment import Repayment
from app.models.user import User
from sqlalchemy import select


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_normalized_replay(b8, action):
    first = b8.decide(action, key="retry", body={"decision_note": " hi "})
    replay = b8.decide(action, key="retry", body={"decision_note": "hi"})
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert len(b8.history().json()) == 1
    with b8.api.factory() as db:
        key = db.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "retry"))
        assert key.endpoint == f"POST /api/v1/repayments/{b8.repayment}/{action}"
        assert key.expires_at - key.created_at == timedelta(days=30)
        assert db.get(Repayment, UUID(b8.repayment)).idempotency_key_id is None


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_changed_note_conflicts(b8, action):
    assert b8.decide(action, key="retry").status_code == 200
    result = b8.decide(action, key="retry", body={"decision_note": "changed"})
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_expired_result_does_not_create_another_decision(b8, action):
    assert b8.decide(action, key="expired").status_code == 200
    with b8.api.factory.begin() as db:
        db.scalar(
            select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "expired")
        ).expires_at = b8.api.clock.now
    assert b8.decide(action, key="expired").json()["error"]["code"] == (
        "ALREADY_VERIFIED" if action == "verify" else "INVALID_STATE"
    )
    assert len(b8.history().json()) == 1


def test_operation_scope_not_replay_of_opposite_action(b8):
    assert b8.decide("dispute", key="same").status_code == 200
    result = b8.decide("verify", key="same")
    assert result.status_code == 409 and result.json()["error"]["code"] == "INVALID_STATE"


def test_resource_and_actor_scope(b8):
    assert b8.decide(key="same").status_code == 200
    another = b8.report(actor="B").json()["id"]
    assert b8.decide(actor="A", identifier=another, key="same").status_code == 200
    assert b8.decide(actor="A", key="same").status_code == 403


@pytest.mark.parametrize("kind", ["revoked", "deactivated", "unrelated", "now_reporter"])
def test_replay_auth_and_action_rechecked(b8, kind):
    assert b8.decide(key="retry").status_code == 200
    with b8.api.factory.begin() as db:
        if kind == "revoked":
            for row in db.scalars(select(AuthSession).where(AuthSession.user_id == b8.users["B"])):
                row.revoked_at = b8.api.clock.now
                row.revocation_reason = "LOGOUT"
        elif kind == "deactivated":
            db.get(User, b8.users["B"]).status = "DEACTIVATED"
        elif kind == "unrelated":
            db.get(Commitment, UUID(b8.identifier)).lender_user_id = b8.users["C"]
        else:
            db.get(Repayment, UUID(b8.repayment)).reported_by_user_id = b8.users["B"]
    result = b8.decide(key="retry")
    assert (
        result.status_code
        == {"revoked": 401, "deactivated": 403, "unrelated": 404, "now_reporter": 403}[kind]
    )


def test_replay_original_response_after_later_full_payment(b8):
    first = b8.decide(key="original").json()
    another = b8.report(amount_minor=9000).json()["id"]
    assert b8.decide(identifier=another).status_code == 200
    assert b8.decide(key="original").json() == first
    with b8.api.factory() as db:
        assert db.get(Commitment, UUID(b8.identifier)).status.value == "FULLY_REPAID"


@pytest.mark.parametrize("failure", ["schema", "authz", "state", "amount"])
def test_failures_not_cached(b8, failure):
    with b8.api.factory.begin() as db:
        if failure == "state":
            db.get(Commitment, UUID(b8.identifier)).status = "CLOSED"
        if failure == "amount":
            db.get(Repayment, UUID(b8.repayment)).amount_minor = 10001
    result = b8.decide(
        key="failure",
        actor="C" if failure == "authz" else "B",
        body={"unknown": 1} if failure == "schema" else {},
    )
    assert result.status_code in (422, 404, 409)
    with b8.api.factory() as db:
        assert (
            db.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "failure"))
            is None
        )


@pytest.mark.parametrize("kind", ["b5", "b7"])
def test_historical_scope_hash_and_replay_unchanged(b8, kind):
    # Independent approved canonical encoding, not the implementation helper.
    if kind == "b5":
        payload = dict(b8.body)
        result = b8.request("POST", key="legacy", json=payload)
        endpoint = "POST /api/v1/commitments"
        resource = None
        operation = "create"

        def replay():
            return b8.request("POST", key="legacy", json=payload)
    else:
        payload = dict(b8.report_body)
        result = b8.report(key="legacy")
        endpoint = f"POST /api/v1/commitments/{b8.identifier}/repayments"
        resource = b8.identifier
        operation = "repayments"

        def replay():
            return b8.report(key="legacy")

    assert result.status_code == 201
    expected = hashlib.sha256(
        json.dumps(
            {
                "actor": str(b8.users["A"]),
                "operation": operation,
                "resource": resource,
                "request": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    with b8.api.factory() as db:
        record = db.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "legacy"))
        assert record.endpoint == endpoint
        assert record.request_hash == expected
    assert replay().json() == result.json()
