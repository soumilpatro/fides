from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from app.models.commitment_terms_version import CommitmentTermsVersion as Terms
from app.models.extension_request import ExtensionRequest
from app.models.ledger_event import LedgerEvent
from app.models.user import User
from sqlalchemy import select

from ledger.test_contract import DETAILS

from .conftest import requested


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_historical_details_current_names_privacy(b10, action):
    identifier = requested(b10, reason="do-not-project-reason")
    b10.api.clock.now += timedelta(seconds=1)
    assert b10.decide(identifier, action).status_code == 200
    with b10.api.factory.begin() as db:
        db.get(User, b10.users["A"]).display_name = "New A"
        db.get(User, b10.users["B"]).display_name = "New B"
    response = b10.timeline()
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    for item in items:
        assert set(item["details"]) == DETAILS[item["event_type"]]
        assert item["actor"]["display_name"] == (
            "New A" if item["actor"]["id"] == str(b10.users["A"]) else "New B"
        )
    extensions = [r for r in items if r["event_type"].startswith("EXTENSION_")]
    assert [r["event_type"] for r in extensions] == [
        "EXTENSION_REQUESTED",
        "EXTENSION_" + action.upper().replace("ACCEPT", "ACCEPTED").replace("REJECT", "REJECTED"),
    ]
    assert all(r["details"]["previous_due_date"] == "2026-10-10" for r in extensions)
    for forbidden in (
        "do-not-project-reason",
        "event_payload",
        "metadata",
        "'request_id':",
        "amount_minor",
        "currency",
    ):
        assert forbidden not in str(extensions)
    assert b10.timeline("B").json() == response.json()
    assert b10.timeline("C").status_code == 404


def test_pagination_across_extension_events(b10):
    for action in ("reject", "accept"):
        identifier = requested(b10)
        assert b10.decide(identifier, action).status_code == 200
    expected = b10.timeline().json()["items"]
    assert len(expected) == 6
    seen = []
    cursor = None
    while True:
        response = b10.api.client.get(
            f"/api/v1/commitments/{b10.identifier}/ledger",
            headers=b10.headers["A"],
            params={"limit": 1, **({"cursor": cursor} if cursor else {})},
        )
        assert response.status_code == 200
        page = response.json()
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == expected
    assert [r["id"] for r in seen] == sorted(r["id"] for r in seen)


@pytest.mark.parametrize("action", ["accept", "reject"])
@pytest.mark.parametrize(
    "kind",
    [
        "extra",
        "missing",
        "bad_uuid",
        "foreign_request",
        "foreign_base",
        "bad_date",
        "bad_actor",
        "money",
        "base_context",
        "request_date",
        "status",
    ],
)
def test_corrupt_references_fail_safe(b10, action, kind):
    identifier = requested(b10)
    assert b10.decide(identifier, action).status_code == 200
    with b10.api.factory.begin() as db:
        row = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.commitment_id == UUID(b10.identifier),
                LedgerEvent.event_type
                == ("EXTENSION_ACCEPTED" if action == "accept" else "EXTENSION_REJECTED"),
            )
        )
        payload = dict(row.event_payload)
        if kind == "extra":
            payload["reason"] = "private-corruption"
        elif kind == "missing":
            del payload["requested_by_user_id"]
        elif kind == "bad_uuid":
            payload["extension_request_id"] = "private-corruption"
        elif kind == "foreign_request":
            payload["extension_request_id"] = str(uuid4())
        elif kind == "foreign_base":
            other = db.scalar(
                select(Terms).where(Terms.commitment_id == UUID(b10.financial.identifier))
            )
            payload["base_terms_version_id"] = str(other.id)
        elif kind == "bad_date":
            payload["previous_due_date"] = "2025-01-01"
        elif kind == "bad_actor":
            row.actor_user_id = b10.users["A"]
        elif kind == "money":
            row.amount_minor = 1
        elif kind == "base_context":
            db.get(ExtensionRequest, UUID(identifier)).requested_terms = {
                "base_terms_version_id": str(uuid4())
            }
        elif kind == "request_date":
            db.get(ExtensionRequest, UUID(identifier)).requested_due_date = date(2027, 1, 1)
        else:
            payload["status"] = "REQUESTED"
        row.event_payload = payload
    response = b10.timeline()
    assert response.status_code == 503
    assert "private-corruption" not in response.text


@pytest.mark.parametrize(
    "field",
    [
        "interest_rate_bps",
        "grace_period_days",
        "due_date",
        "created_by_user_id",
        "effective_at",
        "schedule_definition",
    ],
)
def test_result_version_integrity(b10, field):
    identifier = requested(b10)
    assert b10.decide(identifier).status_code == 200
    with b10.api.factory.begin() as db:
        row = db.scalar(
            select(Terms).where(Terms.commitment_id == UUID(b10.identifier), Terms.version_no == 2)
        )
        setattr(
            row,
            field,
            {
                "interest_rate_bps": 600,
                "grace_period_days": 4,
                "due_date": date(2030, 1, 1),
                "created_by_user_id": b10.users["A"],
                "effective_at": b10.api.clock.now + timedelta(seconds=1),
                "schedule_definition": {"bad": "private-corruption"},
            }[field],
        )
    assert b10.timeline().status_code == 503


@pytest.mark.parametrize("kind", ["metadata", "timezone", "schedule", "creator"])
def test_base_schedule_integrity(b10, kind):
    requested(b10)
    with b10.api.factory.begin() as db:
        row = db.scalar(select(Terms).where(Terms.commitment_id == UUID(b10.identifier)))
        if kind == "creator":
            row.created_by_user_id = b10.users["C"]
        else:
            row.schedule_definition = (
                {"extra": "private-corruption"}
                if kind == "metadata"
                else {**row.schedule_definition, "due_timezone": "invalid-zone"}
                if kind == "timezone"
                else {**row.schedule_definition, "schedule_mode": "installments"}
            )
    assert b10.timeline().status_code == 503


def test_cross_parent_request_reference(b10):
    requested(b10)
    other = b10.commitment(terms={"due_date": "2026-10-10", "interest_type": "NONE"})
    foreign = requested(b10, parent=other)
    with b10.api.factory.begin() as db:
        row = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.commitment_id == UUID(b10.identifier),
                LedgerEvent.event_type == "EXTENSION_REQUESTED",
            )
        )
        row.event_payload = {**row.event_payload, "extension_request_id": foreign}
    assert b10.timeline().status_code == 503
