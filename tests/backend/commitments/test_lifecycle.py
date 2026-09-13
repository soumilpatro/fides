from uuid import UUID, uuid4

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_installment import CommitmentInstallment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.connection import Connection
from app.models.enums import CommitmentStatus
from app.models.ledger_event import LedgerEvent
from app.models.user import User
from sqlalchemy import select


def create(ctx, **changes):
    response = ctx.request("POST", json={**ctx.body, **changes})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("actor", ["A", "B"])
@pytest.mark.parametrize("role", ["BORROWER", "LENDER"])
@pytest.mark.parametrize("kind", ["IOU", "PEER_LOAN"])
@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
def test_creation_direction_types_currencies(ctx, actor, role, kind, currency):
    result = ctx.request(
        "POST",
        actor=actor,
        json={**ctx.body, "actor_role": role, "type": kind, "currency": currency},
    )
    assert result.status_code == 201, result.text
    row = result.json()
    assert row[role.lower()]["id"] == str(ctx.users[actor])
    assert row["creator"]["id"] == str(ctx.users[actor])
    assert row["currency"] == currency and row["type"] == kind
    assert row["status"] == "PENDING_CONFIRMATION"
    assert row["confirmed_at"] is row["activated_at"] is None
    with ctx.api.factory() as db:
        terms = db.scalar(
            select(CommitmentTermsVersion).where(
                CommitmentTermsVersion.commitment_id == UUID(row["id"])
            )
        )
        assert terms.version_no == 1 and terms.interest_type.value == "NONE"
        assert terms.interest_rate_bps is terms.due_date is terms.schedule_definition is None
        assert terms.grace_period_days == 0
        assert (
            db.scalar(
                select(CommitmentInstallment.id).where(
                    CommitmentInstallment.commitment_id == UUID(row["id"])
                )
            )
            is None
        )
        event = db.scalar(select(LedgerEvent).where(LedgerEvent.commitment_id == UUID(row["id"])))
        assert event.event_type == "COMMITMENT_PROPOSED" and event.terms_version_id == terms.id
        assert event.amount_minor is None and event.currency is None
        assert event.event_payload == {"status": "PENDING_CONFIRMATION"}
        assert db.get(Commitment, UUID(row["id"])).closed_at is None


@pytest.mark.parametrize("state", ["PENDING", "BLOCKED", "REMOVED"])
def test_creation_requires_accepted(ctx, state):
    with ctx.api.factory.begin() as db:
        db.get(Connection, UUID(ctx.connection)).status = state
    response = ctx.request("POST", json=ctx.body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"


@pytest.mark.parametrize("state", ["DEACTIVATED", "ANONYMIZED"])
def test_creation_inactive_counterparty(ctx, state):
    with ctx.api.factory.begin() as db:
        db.get(User, ctx.users["B"]).status = state
    assert ctx.request("POST", json=ctx.body).status_code == 404


@pytest.mark.parametrize("actor", ["A", "B", "C"])
@pytest.mark.parametrize("action", ["confirm", "reject", "cancel"])
@pytest.mark.parametrize("state", [s.value for s in CommitmentStatus])
def test_lifecycle_matrix(ctx, actor, action, state):
    row = create(ctx)
    with ctx.api.factory.begin() as db:
        db.get(Commitment, UUID(row["id"])).status = state
    allowed_actor = "A" if action == "cancel" else "B"
    expected = (
        404
        if actor == "C"
        else 403
        if actor != allowed_actor
        else 409
        if state != "PENDING_CONFIRMATION"
        else 200
    )
    response = ctx.request("POST", "/" + row["id"] + "/" + action, actor=actor)
    assert response.status_code == expected, response.text
    with ctx.api.factory() as db:
        persisted = db.get(Commitment, UUID(row["id"]))
        events = list(
            db.scalars(select(LedgerEvent).where(LedgerEvent.commitment_id == persisted.id))
        )
        audits = list(db.scalars(select(AuditLog).where(AuditLog.object_id == persisted.id)))
        assert len(events) == len(audits) == (2 if expected == 200 else 1)
        if expected == 200:
            target, event = {
                "confirm": ("ACTIVE", "COMMITMENT_CONFIRMED"),
                "reject": ("REJECTED", "COMMITMENT_REJECTED"),
                "cancel": ("CANCELLED", "COMMITMENT_CANCELLED"),
            }[action]
            assert persisted.status.value == target
            assert event in {e.event_type for e in events}
            assert event in {a.action for a in audits}
            if action == "confirm":
                assert persisted.confirmed_at == persisted.activated_at == ctx.api.clock.now
            else:
                assert persisted.confirmed_at is persisted.activated_at is None
        else:
            assert persisted.status.value == state
            assert (
                response.json()["error"]["code"]
                == {403: "FORBIDDEN", 404: "NOT_FOUND", 409: "INVALID_STATE"}[expected]
            )


@pytest.mark.parametrize("state", ["PENDING", "BLOCKED", "REMOVED"])
@pytest.mark.parametrize("action", ["confirm", "reject", "cancel"])
def test_later_connection_state(ctx, state, action):
    row = create(ctx)
    with ctx.api.factory.begin() as db:
        db.get(Connection, UUID(ctx.connection)).status = state
    response = ctx.request(
        "POST", "/" + row["id"] + "/" + action, actor="A" if action == "cancel" else "B"
    )
    assert response.status_code == (409 if action == "confirm" else 200)
    for actor in ("A", "B"):
        assert ctx.request("GET", "/" + row["id"], actor=actor).status_code == 200
    assert ctx.request("GET", "/" + row["id"], actor="C").status_code == 404


def test_reads_independence_and_order(ctx):
    rows = [create(ctx), create(ctx), create(ctx, actor_role="LENDER")]
    assert len({r["id"] for r in rows}) == 3
    assert rows[0]["borrower"]["id"] == rows[2]["lender"]["id"]
    assert [r["id"] for r in ctx.request("GET").json()] == sorted(r["id"] for r in rows)
    assert ctx.request("GET", actor="B").json() == ctx.request("GET").json()
    assert ctx.request("GET", actor="C").json() == []
    # A relationship to A does not give C access to A/B obligations.
    new_connection = ctx.call("POST", json={"phone": ctx.phones["C"]}).json()["id"]
    ctx.call("POST", "/" + new_connection + "/accept", actor="C")
    assert ctx.request("GET", "/" + rows[0]["id"], actor="C").status_code == 404
    assert ctx.request("GET", "/" + str(uuid4())).status_code == 404
    ctx.request("POST", "/" + rows[0]["id"] + "/confirm", actor="B")
    assert ctx.request("GET").json()[0]["id"] == rows[0]["id"]
