from uuid import UUID, uuid4

import pytest
from app.models.audit_log import AuditLog
from app.models.ledger_event import LedgerEvent
from sqlalchemy import select


def snapshot(env):
    with env.api.factory() as db:
        ledger = list(
            db.execute(
                select(LedgerEvent.__table__).where(
                    LedgerEvent.commitment_id == UUID(env.identifier)
                )
            )
        )
        audit = list(
            db.execute(
                select(AuditLog.__table__).where(AuditLog.actor_user_id.in_(env.users.values()))
            )
        )
        return ledger, audit


@pytest.mark.parametrize("decision", ["verify", "dispute"])
def test_read_is_immutable(timeline, decision):
    assert timeline.decide(decision).status_code == 200
    before = snapshot(timeline)
    for actor in "AB":
        assert timeline.timeline(actor).status_code == 200
    assert snapshot(timeline) == before


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_b8_replay_no_duplicate_events(timeline, action):
    assert timeline.decide(action, key="b9-decision-replay").status_code == 200
    before = snapshot(timeline)
    first_page = timeline.timeline().json()
    assert timeline.decide(action, key="b9-decision-replay").status_code == 200
    assert snapshot(timeline) == before
    assert timeline.timeline().json() == first_page


def test_b7_replay_no_duplicate_events(timeline):
    assert timeline.report(key="b9-report-replay").status_code == 201
    before = snapshot(timeline)
    assert timeline.report(key="b9-report-replay").status_code == 201
    assert snapshot(timeline) == before


@pytest.mark.parametrize("action,actor", [("confirm", "B"), ("reject", "B"), ("cancel", "A")])
def test_b5_create_and_lifecycle_replay(timeline, action, actor):
    key = "b9-create-replay"
    first = timeline.request("POST", json=timeline.body, key=key)
    assert first.status_code == 201
    identifier = first.json()["id"]
    before = timeline.timeline(identifier=identifier).json()
    audit_before = snapshot(timeline)[1]
    replay = timeline.request("POST", json=timeline.body, key=key)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert timeline.timeline(identifier=identifier).json() == before
    assert snapshot(timeline)[1] == audit_before
    endpoint = f"/{identifier}/{action}"
    assert timeline.request("POST", endpoint, actor=actor, key="b9-action").status_code == 200
    before = timeline.timeline(identifier=identifier).json()
    audit_before = snapshot(timeline)[1]
    assert timeline.request("POST", endpoint, actor=actor, key="b9-action").status_code == 200
    assert timeline.timeline(identifier=identifier).json() == before
    assert snapshot(timeline)[1] == audit_before


@pytest.mark.parametrize("commit", [False, True])
def test_read_committed_visibility(timeline, commit):
    before = timeline.timeline().json()
    identifier = uuid4()
    with timeline.api.factory() as writer:
        writer.add(
            LedgerEvent(
                id=identifier,
                commitment_id=UUID(timeline.identifier),
                actor_user_id=timeline.users["B"],
                event_type="COMMITMENT_CONFIRMED",
                event_payload={"status": "ACTIVE"},
                occurred_at=timeline.api.clock.now,
            )
        )
        writer.flush()
        # Independent connection sees no uncommitted event.
        assert timeline.timeline().json() == before
        if commit:
            writer.commit()
        else:
            writer.rollback()
    after = timeline.timeline().json()
    assert (str(identifier) in {e["id"] for e in after["items"]}) is commit
    if not commit:
        assert after == before


@pytest.mark.parametrize("action", ["verify", "dispute"])
def test_failed_writer_atomicity_visibility(timeline, monkeypatch, action):
    from app.verification import VerificationService

    original = VerificationService._events

    def fail(db, *args):
        original(db, *args)
        db.flush()
        raise ValueError("Simulated writer failure")

    before = snapshot(timeline)
    monkeypatch.setattr(VerificationService, "_events", staticmethod(fail))
    assert timeline.decide(action).status_code == 503
    assert snapshot(timeline) == before
    assert timeline.timeline().status_code == 200
