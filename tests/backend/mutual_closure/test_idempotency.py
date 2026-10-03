from datetime import timedelta
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.mutual_closure_request import MutualClosureRequest
from app.models.user import User
from sqlalchemy import func, select

from .conftest import error, requested


@pytest.mark.parametrize("action", ["create", "accept", "reject", "cancel"])
def test_original_response_and_single_effects(mc, action):
    identifier = None if action == "create" else requested(mc)
    actor = "A" if action in ("create", "cancel") else "B"

    def call():
        return (
            mc.create(key="replay", note="  agreed  ")
            if action == "create"
            else mc.decide(identifier, action, actor=actor, key="replay")
        )

    original = call()
    assert original.status_code == (201 if action == "create" else 200)
    if action == "create":
        assert mc.decide(original.json()["id"]).status_code == 200
        replay = mc.create(key="replay", note="agreed")
    else:
        replay = call()
    assert replay.status_code == original.status_code and replay.json() == original.json()
    with mc.api.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(MutualClosureRequest)
                .where(MutualClosureRequest.commitment_id == UUID(mc.identifier))
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(LedgerEvent)
                .where(
                    LedgerEvent.commitment_id == UUID(mc.identifier),
                    LedgerEvent.event_type
                    == "MUTUAL_CLOSURE_"
                    + (
                        "REQUESTED"
                        if action == "create"
                        else action.upper()
                        .replace("REJECT", "REJECTED")
                        .replace("ACCEPT", "ACCEPTED")
                        .replace("CANCEL", "CANCELLED")
                    ),
                )
            )
            == 1
        )


def test_conflicting_payload(mc):
    assert mc.create(key="same", note="first").status_code == 201
    error(mc.create(key="same", note="second"), "IDEMPOTENCY_CONFLICT")


def test_endpoint_scopes_are_independent(mc):
    identifier = requested(mc, key="scope")
    assert mc.decide(identifier, "cancel", actor="A", key="scope").status_code == 200
    with mc.api.factory() as db:
        keys = list(
            db.scalars(
                select(IdempotencyKey.endpoint).where(
                    IdempotencyKey.user_id == mc.users["A"],
                    IdempotencyKey.idempotency_key == "scope",
                )
            )
        )
    assert set(keys) == {
        f"POST /api/v1/commitments/{mc.identifier}/closure-requests",
        f"POST /api/v1/closure-requests/{identifier}/cancel",
    }


@pytest.mark.parametrize("action", ["create", "accept", "reject", "cancel"])
def test_replay_current_auth(mc, action):
    identifier = None if action == "create" else requested(mc)
    actor = "A" if action in ("create", "cancel") else "B"

    def call():
        return (
            mc.create(key="auth")
            if action == "create"
            else mc.decide(identifier, action, actor=actor, key="auth")
        )

    assert call().status_code in (200, 201)
    with mc.api.factory.begin() as db:
        db.get(User, mc.users[actor]).status = "DEACTIVATED"
    error(call(), "ACCOUNT_DEACTIVATED", 403)


def test_expired_key_is_fresh_and_failed_transaction_does_not_consume(mc):
    identifier = requested(mc, key="expiry")
    assert mc.decide(identifier, "cancel", actor="A").status_code == 200
    with mc.api.factory.begin() as db:
        key = db.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == mc.users["A"], IdempotencyKey.idempotency_key == "expiry"
            )
        )
        assert key.expires_at - key.created_at == timedelta(days=30)
        key.expires_at = mc.api.clock.now
    fresh = mc.create(key="expiry")
    assert fresh.status_code == 201 and fresh.json()["id"] != identifier
    error(mc.create(key="failed"), "CONFLICT")
    with mc.api.factory() as db:
        assert (
            db.scalar(
                select(IdempotencyKey.id).where(
                    IdempotencyKey.user_id == mc.users["A"],
                    IdempotencyKey.idempotency_key == "failed",
                )
            )
            is None
        )


def test_replay_parent_authorization_rechecked(mc):
    result = mc.create(key="membership")
    with mc.api.factory.begin() as db:
        db.get(Commitment, UUID(mc.identifier)).borrower_user_id = mc.users["C"]
    error(mc.create(key="membership"), "NOT_FOUND", 404)
    assert result.status_code == 201
