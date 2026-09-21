from datetime import timedelta
from uuid import UUID

import pytest
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.extension_request import ExtensionRequest
from app.models.idempotency_key import IdempotencyKey
from app.models.user import User
from sqlalchemy import select

from .conftest import requested
from .test_atomicity import snapshot


@pytest.mark.parametrize("action", ["create", "accept", "reject"])
def test_original_replay_no_effects(b10, action):
    identifier = requested(b10) if action != "create" else None

    def run():
        return (
            b10.create(key="retry", reason="  hello  ")
            if action == "create"
            else b10.decide(identifier, action, key="retry")
        )

    original = run()
    assert original.status_code == (201 if action == "create" else 200)
    before = snapshot(b10)
    assert run().json() == original.json()
    assert snapshot(b10) == before
    with b10.api.factory() as db:
        key = db.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "retry"))
        assert key.expires_at - key.created_at == timedelta(days=30)
        assert key.endpoint == (
            f"POST /api/v1/commitments/{b10.identifier}/extension-requests"
            if action == "create"
            else f"POST /api/v1/extension-requests/{identifier}/{action}"
        )
    if action == "create":
        assert b10.create(key="retry", reason="hello").json() == original.json()
        assert b10.decide(original.json()["id"], "reject").status_code == 200
        assert run().json() == original.json()


@pytest.mark.parametrize("change", [{"reason": "changed"}, {"requested_due_date": "2026-12-01"}])
def test_changed_body_conflict(b10, change):
    requested(b10, key="same")
    result = b10.create(key="same", **change)
    assert result.status_code == 409 and result.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("action", ["create", "accept", "reject"])
def test_expiry_rechecks_current_state(b10, action):
    identifier = requested(b10, key="retry" if action == "create" else "original")
    if action != "create":
        assert b10.decide(identifier, action, key="retry").status_code == 200
    with b10.api.factory.begin() as db:
        db.scalar(
            select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "retry")
        ).expires_at = b10.api.clock.now
    result = (
        b10.create(key="retry")
        if action == "create"
        else b10.decide(identifier, action, key="retry")
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == ("CONFLICT" if action == "create" else "INVALID_STATE")


def test_resource_action_actor_isolation(b10):
    first = requested(b10, key="same")
    assert b10.decide(first, "reject", key="same").status_code == 200
    assert b10.decide(first, "accept", key="same").json()["error"]["code"] == "INVALID_STATE"
    second = requested(b10, actor="B", key="same")
    assert second != first
    assert b10.decide(second, "reject", actor="A", key="same").status_code == 200
    other = b10.commitment(terms={"due_date": "2026-10-10", "interest_type": "NONE"})
    assert requested(b10, parent=other, key="same") not in (first, second)


@pytest.mark.parametrize("kind", ["revoked", "inactive", "unrelated", "self"])
def test_replay_reauth_and_authz(b10, kind):
    identifier = requested(b10)
    assert b10.decide(identifier, key="replay").status_code == 200
    with b10.api.factory.begin() as db:
        if kind == "revoked":
            for row in db.scalars(select(AuthSession).where(AuthSession.user_id == b10.users["B"])):
                row.revoked_at = b10.api.clock.now
                row.revocation_reason = "LOGOUT"
        elif kind == "inactive":
            db.get(User, b10.users["B"]).status = "DEACTIVATED"
        elif kind == "unrelated":
            db.get(Commitment, UUID(b10.identifier)).lender_user_id = b10.users["C"]
        else:
            db.get(ExtensionRequest, UUID(identifier)).requested_by_user_id = b10.users["B"]
    assert (
        b10.decide(identifier, key="replay").status_code
        == {"revoked": 401, "inactive": 403, "unrelated": 404, "self": 403}[kind]
    )


@pytest.mark.parametrize("failure", ["schema", "authz", "date", "state"])
def test_failures_not_cached(b10, failure):
    if failure == "state":
        with b10.api.factory.begin() as db:
            db.get(Commitment, UUID(b10.identifier)).status = "CLOSED"
    response = b10.create(
        key="failure",
        actor="C" if failure == "authz" else "A",
        **(
            {"unknown": 1}
            if failure == "schema"
            else {"requested_due_date": "2020-01-01"}
            if failure == "date"
            else {}
        ),
    )
    assert response.status_code in (422, 404, 409)
    with b10.api.factory() as db:
        assert (
            db.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "failure"))
            is None
        )
