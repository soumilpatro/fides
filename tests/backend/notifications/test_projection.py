from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.models.ledger_event import LedgerEvent
from sqlalchemy import select

from .conftest import TYPES, make, notification_row, notifications
from .test_contract import FIELDS


@pytest.mark.parametrize("kind", TYPES)
def test_private_content_never_copied(inbox, kind, caplog):
    identifier = make(inbox, kind)
    result = inbox.mark(identifier)
    assert result.status_code == 200, result.text
    assert set(result.json()) == FIELDS
    row = notifications(inbox)[identifier]
    assert set(row["payload"]) == {"source_ledger_event_id"}
    combined = result.text + str(row["payload"]) + caplog.text
    for secret in (
        "private-commitment-description",
        "private-report-note",
        "private-verification-note",
        "private-extension-reason",
        *inbox.phones.values(),
    ):
        assert secret not in combined
    for field in (
        "payload",
        "object_id",
        "object_type",
        "source_ledger_event_id",
        "status",
        "sent_at",
        "scheduled_at",
        "amount_minor",
        "currency",
        "previous_due_date",
        "requested_due_date",
        "note",
        "reason",
        "description",
        "title",
        "body",
        "is_read",
    ):
        assert field not in result.json()


@pytest.mark.parametrize(
    "kind",
    [
        "unknown_type",
        "null_payload",
        "extra_payload",
        "bad_uuid",
        "numeric_uuid",
        "missing_event",
        "wrong_type",
        "wrong_object_type",
        "wrong_object_id",
        "foreign_parent",
        "bad_actor",
        "self_recipient",
        "third_recipient",
        "pending",
        "sent",
        "failed",
        "read_without_time",
        "delivered_with_time",
        "time_before_creation",
        "sent_at",
        "scheduled_at",
    ],
)
@pytest.mark.parametrize("operation", ["list", "read"])
def test_corruption_fails_closed(inbox, kind, operation):
    identifier = make(inbox)
    actor = "B"
    with inbox.api.factory.begin() as db:
        row = notification_row(db, identifier)
        source = db.get(LedgerEvent, UUID(row.payload["source_ledger_event_id"]))
        if kind == "unknown_type":
            row.type = "PRIVATE_UNSUPPORTED"
        elif kind == "null_payload":
            row.payload = {}
        elif kind == "extra_payload":
            row.payload = {**row.payload, "reason": "private-corruption"}
        elif kind == "bad_uuid":
            row.payload = {"source_ledger_event_id": "private-corruption"}
        elif kind == "numeric_uuid":
            row.payload = {"source_ledger_event_id": 123}
        elif kind == "missing_event":
            row.payload = {"source_ledger_event_id": str(uuid4())}
        elif kind == "wrong_type":
            row.type = "REPAYMENT_REPORTED"
        elif kind == "wrong_object_type":
            row.object_type = "Repayment"
        elif kind == "wrong_object_id":
            row.object_id = uuid4()
        elif kind == "foreign_parent":
            other = db.scalar(
                select(LedgerEvent).where(
                    LedgerEvent.commitment_id == UUID(inbox.identifier),
                    LedgerEvent.event_type == "COMMITMENT_PROPOSED",
                )
            )
            row.payload = {"source_ledger_event_id": str(other.id)}
        elif kind == "bad_actor":
            source.actor_user_id = inbox.users["C"]
        elif kind in ("self_recipient", "third_recipient"):
            actor = "A" if kind == "self_recipient" else "C"
            row.user_id = inbox.users[actor]
        elif kind in ("pending", "sent", "failed"):
            row.status = kind.upper()
        elif kind == "read_without_time":
            row.status = "READ"
        elif kind == "delivered_with_time":
            row.read_at = inbox.api.clock.now
        elif kind == "time_before_creation":
            row.status = "READ"
            row.read_at = row.created_at - timedelta(seconds=1)
        else:
            setattr(row, kind, inbox.api.clock.now)
    before = notifications(inbox)
    response = inbox.inbox(actor) if operation == "list" else inbox.mark(identifier, actor)
    assert response.status_code == 503, response.text
    assert response.json() == {
        "error": {"code": "SERVICE_UNAVAILABLE", "message": "Service is temporarily unavailable."}
    }
    assert "private-corruption" not in response.text
    assert notifications(inbox) == before


@pytest.mark.parametrize(
    "kind", ["REPAYMENT_VERIFIED", "REPAYMENT_DISPUTED", "EXTENSION_ACCEPTED", "EXTENSION_REJECTED"]
)
def test_corrupt_nested_provenance(inbox, kind):
    identifier = make(inbox, kind)
    with inbox.api.factory.begin() as db:
        row = notification_row(db, identifier)
        source = db.get(LedgerEvent, UUID(row.payload["source_ledger_event_id"]))
        key = "verification_id" if kind.startswith("REPAYMENT") else "extension_request_id"
        source.event_payload = {**source.event_payload, key: str(uuid4())}
    assert inbox.inbox().status_code == 503
    assert inbox.mark(identifier).status_code == 503


def test_sql_bind_logging_private(inbox, caplog):
    engine = inbox.api.factory.kw["bind"]
    engine.echo = True
    try:
        identifier = make(inbox, "EXTENSION_REQUESTED")
        assert inbox.inbox().status_code == 200
        assert inbox.mark(identifier).status_code == 200
    finally:
        engine.echo = False
    assert "private-extension-reason" not in caplog.text
