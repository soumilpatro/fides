from uuid import UUID, uuid4

import pytest
from app.models.audit_log import AuditLog
from app.models.commitment import Commitment
from app.models.ledger_event import LedgerEvent
from app.models.notification_event import NotificationEvent
from app.models.notification_preference import NotificationPreference
from sqlalchemy import select

from .conftest import error, requested


@pytest.mark.parametrize("action", ["accept", "reject", "cancel"])
def test_exact_provenance_and_historical_projection(mc, action, caplog):
    for actor in "AB":
        with mc.api.factory.begin() as db:
            db.add(
                NotificationPreference(
                    user_id=mc.users[actor],
                    due_reminders_enabled=False,
                    overdue_reminders_enabled=False,
                )
            )
    identifier = requested(mc, note="private closure note")
    actor = "A" if action == "cancel" else "B"
    assert mc.decide(identifier, action, actor=actor).status_code == 200
    timeline = mc.timeline()
    assert timeline.status_code == 200, timeline.text
    items = [e for e in timeline.json()["items"] if e["event_type"].startswith("MUTUAL_CLOSURE_")]
    assert len(items) == 2
    for item in items:
        status = item["event_type"].removeprefix("MUTUAL_CLOSURE_")
        assert item["actor"]["id"] == str(
            mc.users["A" if status in ("REQUESTED", "CANCELLED") else "B"]
        )
        expected = dict(
            closure_request_id=identifier,
            status=status,
            currency="INR",
            outstanding_snapshot_minor=10000,
            waived_amount_minor=10000,
        )
        if status == "ACCEPTED":
            expected["resulting_commitment_status"] = "CLOSED"
        assert item["details"] == expected
    with mc.api.factory() as db:
        events = list(
            db.scalars(
                select(LedgerEvent).where(
                    LedgerEvent.event_type.like("MUTUAL_CLOSURE_%"),
                    LedgerEvent.commitment_id == UUID(mc.identifier),
                )
            )
        )
        for event in events:
            assert event.event_payload == {
                "closure_request_id": identifier,
                "status": event.event_type.removeprefix("MUTUAL_CLOSURE_"),
            }
            assert (
                event.amount_minor
                is event.currency
                is event.repayment_id
                is event.terms_version_id
                is None
            )
        audits = list(db.scalars(select(AuditLog).where(AuditLog.object_id == UUID(identifier))))
        assert {r.action for r in audits} == {r.event_type for r in events}
        assert all(set(r.metadata_) == {"request_id"} for r in audits)
        notices = list(
            db.scalars(
                select(NotificationEvent).where(NotificationEvent.object_id == UUID(identifier))
            )
        )
        assert len(notices) == (1 if action == "cancel" else 2)
        assert {n.type for n in notices} == {
            e.event_type for e in events if e.event_type != "MUTUAL_CLOSURE_CANCELLED"
        }
        assert all(
            n.dedupe_key is None and n.object_type == "MutualClosureRequest" for n in notices
        )
        assert all(set(n.payload) == {"source_ledger_event_id"} for n in notices)
    for user in "AB":
        inbox = mc.api.client.get("/api/v1/notifications", headers=mc.headers[user])
        assert inbox.status_code == 200, inbox.text
        closure_items = [
            i for i in inbox.json()["items"] if i["type"].startswith("MUTUAL_CLOSURE_")
        ]
        for item in closure_items:
            assert item["actor"]["id"] != str(mc.users[user])
            assert item["commitment_id"] == mc.identifier
            assert item["repayment_id"] is item["extension_request_id"] is None
            assert "closure_request_id" not in item
    assert "private closure note" not in timeline.text + caplog.text


def test_notification_owner_boundary(mc):
    identifier = requested(mc)
    with mc.api.factory() as db:
        notice = db.scalar(
            select(NotificationEvent).where(NotificationEvent.object_id == UUID(identifier))
        )
        nid = notice.id
    for actor in "AC":
        error(
            mc.api.client.post(
                f"/api/v1/notifications/{nid}/read", json={}, headers=mc.headers[actor]
            ),
            "NOT_FOUND",
            404,
        )
    assert (
        mc.api.client.post(
            f"/api/v1/notifications/{nid}/read", json={}, headers=mc.headers["B"]
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "damage",
    ["extra_payload", "foreign_request", "bad_status", "actor", "timestamp", "money", "terms"],
)
def test_invalid_timeline_source_is_safe(mc, damage):
    identifier = requested(mc)
    with mc.api.factory.begin() as db:
        event = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.commitment_id == UUID(mc.identifier),
                LedgerEvent.event_type == "MUTUAL_CLOSURE_REQUESTED",
            )
        )
        if damage == "extra_payload":
            event.event_payload = {**event.event_payload, "note": "must not leak"}
        elif damage == "foreign_request":
            event.event_payload = {"closure_request_id": str(uuid4()), "status": "REQUESTED"}
        elif damage == "bad_status":
            event.event_payload = {"closure_request_id": identifier, "status": "ACCEPTED"}
        elif damage == "actor":
            event.actor_user_id = mc.users["B"]
        elif damage == "timestamp":
            from datetime import timedelta

            event.occurred_at += timedelta(seconds=1)
        elif damage == "money":
            event.amount_minor = 10000
        else:
            from app.models.commitment_terms_version import CommitmentTermsVersion

            event.terms_version_id = db.scalar(
                select(CommitmentTermsVersion.id).where(
                    CommitmentTermsVersion.commitment_id == UUID(mc.identifier)
                )
            )
    error(mc.timeline(), "SERVICE_UNAVAILABLE", 503)
    error(
        mc.api.client.get("/api/v1/notifications", headers=mc.headers["B"]),
        "SERVICE_UNAVAILABLE",
        503,
    )


@pytest.mark.parametrize("damage", ["object_type", "object_id", "source", "recipient"])
def test_notification_provenance_rejected(mc, damage):
    identifier = requested(mc)
    owner = "B"
    with mc.api.factory.begin() as db:
        row = db.scalar(
            select(NotificationEvent).where(NotificationEvent.object_id == UUID(identifier))
        )
        if damage == "object_type":
            row.object_type = "ExtensionRequest"
        elif damage == "object_id":
            row.object_id = uuid4()
        elif damage == "source":
            row.payload = {"source_ledger_event_id": str(uuid4())}
        else:
            row.user_id = mc.users["C"]
            owner = "C"
    error(
        mc.api.client.get("/api/v1/notifications", headers=mc.headers[owner]),
        "SERVICE_UNAVAILABLE",
        503,
    )


def test_accepted_parent_provenance_fails_closed(mc):
    identifier = requested(mc)
    assert mc.decide(identifier).status_code == 200
    with mc.api.factory.begin() as db:
        db.get(Commitment, UUID(mc.identifier)).status = "ACTIVE"
    error(mc.closure_read(identifier=identifier), "SERVICE_UNAVAILABLE", 503)
    error(mc.timeline(), "SERVICE_UNAVAILABLE", 503)
