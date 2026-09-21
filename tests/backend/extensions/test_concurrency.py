from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.connection import Connection
from app.models.extension_request import ExtensionRequest
from app.models.user import User
from sqlalchemy import event, func, select

from .conftest import requested
from .test_versions import versions


def race(*actions):
    barrier = Barrier(len(actions))

    def run(action):
        barrier.wait(timeout=10)
        return action()

    with ThreadPoolExecutor(len(actions)) as pool:
        futures = [pool.submit(run, action) for action in actions]
        return [f.result(timeout=20) for f in futures]


def test_competing_proposals(b10):
    results = race(b10.create, lambda: b10.create(actor="B"))
    assert sorted(r.status_code for r in results) == [201, 409]
    assert next(r for r in results if r.status_code == 409).json()["error"]["code"] == "CONFLICT"
    assert len(b10.read().json()) == 1


@pytest.mark.parametrize(
    "actions", [("accept", "accept"), ("accept", "reject"), ("reject", "reject")]
)
def test_decision_race(b10, actions):
    identifier = requested(b10)
    results = race(*(lambda action=a: b10.decide(identifier, action) for a in actions))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert (
        next(r for r in results if r.status_code == 409).json()["error"]["code"] == "INVALID_STATE"
    )
    winner = next(r.json()["status"] for r in results if r.status_code == 200)
    assert b10.read().json()[0]["status"] == winner
    assert len(versions(b10)) == (2 if winner == "ACCEPTED" else 1)


@pytest.mark.parametrize("operation", ["create", "accept", "reject"])
def test_inflight_and_replay(b10, operation):
    identifier = requested(b10) if operation != "create" else None

    def call():
        return (
            b10.create(key="inflight")
            if operation == "create"
            else b10.decide(identifier, operation, key="inflight")
        )

    entered, release = Event(), Event()

    def hold(*args):
        entered.set()
        assert release.wait(15)

    hook = "before_insert" if operation == "create" else "before_update"
    event.listen(ExtensionRequest, hook, hold)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(call)
            try:
                assert entered.wait(10)
                result = call()
                assert result.status_code == 409 and result.json()["error"]["code"] == "CONFLICT"
            finally:
                release.set()
            original = future.result(timeout=20)
        assert original.status_code == (201 if operation == "create" else 200)
        assert call().json() == original.json()
    finally:
        release.set()
        event.remove(ExtensionRequest, hook, hold)


def test_proposal_report(b10):
    results = race(b10.create, lambda: b10.report(parent=b10.identifier))
    assert [r.status_code for r in results] == [201, 201]


def test_accept_verification(b10):
    report = b10.report(parent=b10.identifier).json()["id"]
    identifier = requested(b10)
    results = race(lambda: b10.decide(identifier), lambda: b10.financial.decide(identifier=report))
    assert [r.status_code for r in results] == [200, 200]
    assert len(versions(b10)) == 2


@pytest.mark.parametrize("operation", ["create", "accept", "reject"])
def test_deactivation_coordination(b10, operation):
    identifier = requested(b10) if operation != "create" else None
    results = race(
        lambda: b10.create() if operation == "create" else b10.decide(identifier, operation),
        lambda: b10.api.client.post("/api/v1/me/deactivate", headers=b10.headers["A"]),
    )
    assert results[0].status_code == (201 if operation == "create" else 200)
    assert results[1].status_code == 409
    assert results[1].json()["error"]["code"] == "ACCOUNT_HAS_UNRESOLVED_COMMITMENTS"


def test_independent_commitments(b10):
    other = b10.commitment(terms={"due_date": "2026-10-10", "interest_type": "NONE"})
    results = race(b10.create, lambda: b10.create(parent=other))
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json()["commitment_id"] != results[1].json()["commitment_id"]


def test_connection_lock_not_required(b10):
    with b10.api.factory.begin() as writer:
        writer.scalar(
            select(Connection).where(Connection.id == UUID(b10.connection)).with_for_update()
        )
        with ThreadPoolExecutor(1) as pool:
            result = pool.submit(b10.create).result(timeout=10)
        assert result.status_code == 201


@pytest.mark.parametrize("kind", ["actor", "counterparty", "parent", "request", "base"])
def test_authoritative_recheck_after_wait(b10, kind):
    identifier = requested(b10)
    reached = Event()
    engine = b10.api.factory.kw["bind"]

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            reached.set()

    with b10.api.factory.begin() as writer:
        for user in sorted([b10.users["A"], b10.users["B"]]):
            writer.scalar(select(User).where(User.id == user).with_for_update())
        parent = writer.scalar(
            select(Commitment).where(Commitment.id == UUID(b10.identifier)).with_for_update()
        )
        event.listen(engine, "before_cursor_execute", observe)
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(b10.decide, identifier)
            try:
                assert reached.wait(10)
                if kind in ("actor", "counterparty"):
                    writer.get(
                        User, b10.users["B" if kind == "actor" else "A"]
                    ).status = "DEACTIVATED"
                elif kind == "parent":
                    parent.status = "CLOSED"
                elif kind == "request":
                    writer.get(ExtensionRequest, UUID(identifier)).status = "CANCELLED"
                else:
                    old = writer.scalar(
                        select(CommitmentTermsVersion).where(
                            CommitmentTermsVersion.commitment_id == parent.id
                        )
                    )
                    writer.add(
                        CommitmentTermsVersion(
                            commitment_id=parent.id,
                            version_no=2,
                            effective_at=b10.api.clock.now,
                            due_date=old.due_date,
                            interest_type=old.interest_type,
                            interest_rate_bps=old.interest_rate_bps,
                            grace_period_days=old.grace_period_days,
                            schedule_definition=old.schedule_definition,
                            created_by_user_id=b10.users["A"],
                        )
                    )
                writer.commit()
                response = future.result(timeout=20)
            finally:
                writer.rollback()
                event.remove(engine, "before_cursor_execute", observe)
    assert (
        response.status_code
        == {"actor": 403, "counterparty": 503, "parent": 409, "request": 409, "base": 409}[kind]
    )
    with b10.api.factory() as db:
        assert db.scalar(
            select(func.count())
            .select_from(CommitmentTermsVersion)
            .where(CommitmentTermsVersion.commitment_id == UUID(b10.identifier))
        ) == (2 if kind == "base" else 1)


def test_lock_order(b10):
    identifier = requested(b10)
    trace = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement:
            trace.append((statement, parameters))

    engine = b10.api.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert b10.decide(identifier).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert all("FROM users" in item[0] for item in trace[:2])
    assert [next(iter(item[1].values())) for item in trace[:2]] == sorted(
        [b10.users["A"], b10.users["B"]]
    )
    assert "FROM commitments" in trace[-2][0]
    assert "FROM extension_requests" in trace[-1][0]
    assert not any("FROM connections" in item[0] for item in trace)
