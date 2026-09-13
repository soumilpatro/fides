from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.connection import Connection
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.user import User
from sqlalchemy import event, select

from .test_lifecycle import create


def counts(ctx, identifier):
    with ctx.api.factory() as db:
        return [
            len(list(db.scalars(select(model.id).where(column == identifier))))
            for model, column in (
                (Commitment, Commitment.id),
                (CommitmentTermsVersion, CommitmentTermsVersion.commitment_id),
                (LedgerEvent, LedgerEvent.commitment_id),
                (AuditLog, AuditLog.object_id),
            )
        ]


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_creates(ctx, same_key):
    barrier = Barrier(2)

    def run(i):
        barrier.wait(timeout=10)
        return ctx.request("POST", key="same" if same_key else str(i), json=ctx.body)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, range(2)))
    assert all(r.status_code in (201, 409) for r in results)
    if same_key:
        ids = {r.json()["id"] for r in results if r.status_code == 201}
        assert len(ids) == 1
        assert counts(ctx, UUID(ids.pop())) == [1, 1, 1, 1]
    else:
        assert all(r.status_code == 201 for r in results)
        assert len({r.json()["id"] for r in results}) == 2


def test_inflight_duplicate_returns_conflict(ctx):
    entered, release = Event(), Event()

    def hold(mapper, connection, target):
        entered.set()
        assert release.wait(10)

    event.listen(Commitment, "before_insert", hold)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(ctx.request, "POST", key="inflight", json=ctx.body)
            try:
                assert entered.wait(10)
                duplicate = ctx.request("POST", key="inflight", json=ctx.body)
                assert duplicate.status_code == 409
                assert duplicate.json()["error"]["code"] == "CONFLICT"
            finally:
                release.set()
            result = future.result(timeout=15)
        assert result.status_code == 201
        assert ctx.request("POST", key="inflight", json=ctx.body).json() == result.json()
    finally:
        release.set()
        event.remove(Commitment, "before_insert", hold)


@pytest.mark.parametrize(
    "actions",
    [("confirm", "confirm"), ("confirm", "reject"), ("confirm", "cancel"), ("reject", "cancel")],
)
def test_competing_lifecycle(ctx, actions):
    row = create(ctx)
    barrier = Barrier(2)

    def run(action):
        barrier.wait(timeout=10)
        return ctx.request(
            "POST", "/" + row["id"] + "/" + action, actor="A" if action == "cancel" else "B"
        )

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, actions))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert (
        next(r for r in results if r.status_code == 409).json()["error"]["code"] == "INVALID_STATE"
    )
    assert counts(ctx, UUID(row["id"])) == [1, 1, 2, 2]
    with ctx.api.factory() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(IdempotencyKey.id).where(
                            IdempotencyKey.user_id.in_(ctx.users.values())
                        )
                    )
                )
            )
            == 2
        )


@pytest.mark.parametrize("kind", ["account", "connection"])
def test_create_rechecks_after_lock_wait(ctx, kind):
    reached = Event()
    engine = ctx.api.factory.kw["bind"]
    table = "users" if kind == "account" else "connections"

    def observe(connection, cursor, statement, parameters, context, executemany):
        if "FROM " + table in statement and "FOR UPDATE" in statement:
            reached.set()

    with ctx.api.factory.begin() as writer:
        model, identifier = (
            (User, ctx.users["B"]) if kind == "account" else (Connection, UUID(ctx.connection))
        )
        locked = writer.scalar(select(model).where(model.id == identifier).with_for_update())
        event.listen(engine, "before_cursor_execute", observe)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(ctx.request, "POST", json=ctx.body)
            try:
                assert reached.wait(10)
                locked.status = "DEACTIVATED" if kind == "account" else "BLOCKED"
                writer.commit()
                response = future.result(timeout=15)
            finally:
                writer.rollback()
                event.remove(engine, "before_cursor_execute", observe)
    assert response.status_code == (404 if kind == "account" else 409)


def test_create_races_actual_b2_deactivation(ctx):
    barrier = Barrier(2)

    def propose():
        barrier.wait(timeout=10)
        return ctx.request("POST", json=ctx.body)

    def deactivate():
        barrier.wait(timeout=10)
        return ctx.api.client.post("/api/v1/me/deactivate", headers=ctx.headers["B"])

    with ThreadPoolExecutor(2) as pool:
        proposal = pool.submit(propose)
        deactivation = pool.submit(deactivate)
        first, second = proposal.result(timeout=15), deactivation.result(timeout=15)
    assert (first.status_code, second.status_code) in ((201, 409), (404, 200))
    with ctx.api.factory() as db:
        user = db.get(User, ctx.users["B"])
        rows = list(
            db.scalars(
                select(Commitment.id).where(Commitment.connection_id == UUID(ctx.connection))
            )
        )
        assert (user.status.value, len(rows)) in (("ACTIVE", 1), ("DEACTIVATED", 0))


def test_confirm_waits_for_connection_state(ctx):
    row = create(ctx)
    reached = Event()
    engine = ctx.api.factory.kw["bind"]

    def observe(connection, cursor, statement, parameters, context, executemany):
        if "FROM connections" in statement and "FOR UPDATE" in statement:
            reached.set()

    with ctx.api.factory.begin() as writer:
        locked = writer.scalar(
            select(Connection).where(Connection.id == UUID(ctx.connection)).with_for_update()
        )
        event.listen(engine, "before_cursor_execute", observe)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(ctx.request, "POST", "/" + row["id"] + "/confirm", actor="B")
            try:
                assert reached.wait(10)
                locked.status = "BLOCKED"
                writer.commit()
                response = future.result(timeout=15)
            finally:
                writer.rollback()
                event.remove(engine, "before_cursor_execute", observe)
    assert response.status_code == 409
    assert counts(ctx, UUID(row["id"])) == [1, 1, 1, 1]
