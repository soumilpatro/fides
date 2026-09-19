from datetime import timedelta
from uuid import UUID

import pytest
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.idempotency_key import IdempotencyKey
from app.models.repayment import Repayment
from app.models.user import User
from sqlalchemy import select


def test_normalized_replay_and_null_fk(b7):
    first = b7.report(key="retry", note=" hello ")
    second = b7.report(key="retry", note="hello")
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    with b7.api.factory() as db:
        rows = list(
            db.scalars(select(Repayment).where(Repayment.commitment_id == UUID(b7.identifier)))
        )
        assert len(rows) == 1 and rows[0].idempotency_key_id is None
        key = db.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "retry"))
        assert key.expires_at - key.created_at == timedelta(days=30)


@pytest.mark.parametrize(
    "change",
    [
        {"amount_minor": 999},
        {"currency": "USD"},
        {"payment_date": "2026-09-10"},
        {"note": "changed"},
    ],
)
def test_changed_payload_conflicts(b7, change):
    assert b7.report(key="retry").status_code == 201
    result = b7.report(key="retry", **change)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("kind", ["actor", "resource"])
def test_scope_isolation(b7, kind):
    first = b7.report(key="same").json()
    second = b7.report(
        key="same", **({"actor": "B"} if kind == "actor" else {"parent": b7.commitment()})
    )
    assert second.status_code == 201
    assert first["id"] != second.json()["id"]


@pytest.mark.parametrize("kind", ["state", "capacity", "terms", "date"])
def test_replay_returns_original_without_rechecking_business_rules(b7, kind):
    first = b7.report(key="original", amount_minor=10000)
    with b7.api.factory.begin() as db:
        if kind == "state":
            db.get(Commitment, UUID(b7.identifier)).status = "CLOSED"
        elif kind == "terms":
            from app.models.commitment_terms_version import CommitmentTermsVersion

            db.scalar(
                select(CommitmentTermsVersion).where(
                    CommitmentTermsVersion.commitment_id == UUID(b7.identifier)
                )
            ).schedule_definition = {"bad": True}
        elif kind == "date":
            db.get(User, b7.users["A"]).timezone = "invalid/zone"
        # Capacity case: first report already reserved all capacity.
    replay = b7.report(key="original", amount_minor=10000)
    assert replay.status_code == 201
    assert replay.json() == first.json()


@pytest.mark.parametrize("kind", ["deactivated", "revoked", "unrelated"])
def test_replay_reauthenticates_and_reauthorizes(b7, kind):
    assert b7.report(key="retry").status_code == 201
    with b7.api.factory.begin() as db:
        if kind == "deactivated":
            db.get(User, b7.users["A"]).status = "DEACTIVATED"
        elif kind == "revoked":
            rows = db.scalars(select(AuthSession).where(AuthSession.user_id == b7.users["A"]))
            for row in rows:
                row.revoked_at = b7.api.clock.now
                row.revocation_reason = "LOGOUT"
        else:
            db.get(Commitment, UUID(b7.identifier)).borrower_user_id = b7.users["C"]
    result = b7.report(key="retry")
    assert result.status_code == {"deactivated": 403, "revoked": 401, "unrelated": 404}[kind]


@pytest.mark.parametrize("failure", ["schema", "authz", "capacity"])
def test_failures_not_cached(b7, failure):
    args = (
        {"amount_minor": False}
        if failure == "schema"
        else {"actor": "C"}
        if failure == "authz"
        else {"amount_minor": 10001}
    )
    assert b7.report(key="retry", **args).status_code in (422, 404, 409)
    with b7.api.factory() as db:
        assert (
            db.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "retry"))
            is None
        )
    assert b7.report(key="retry").status_code == 201


def test_expired_result_reused_without_durable_fk(b7):
    first = b7.report(key="expired").json()
    with b7.api.factory.begin() as db:
        db.scalar(
            select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "expired")
        ).expires_at = b7.api.clock.now
    second = b7.report(key="expired").json()
    assert second["id"] != first["id"]
    with b7.api.factory() as db:
        assert all(
            r.idempotency_key_id is None
            for r in db.scalars(
                select(Repayment).where(Repayment.commitment_id == UUID(b7.identifier))
            )
        )
