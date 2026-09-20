from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.ledger_event import LedgerEvent
from app.models.user import User
from sqlalchemy import select

from .conftest import event


@pytest.mark.parametrize("decision", ["verify", "dispute"])
@pytest.mark.parametrize("actor", ["A", "B"])
def test_writer_projection(timeline, decision, actor):
    assert timeline.decide(decision).status_code == 200
    response = timeline.timeline(actor)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    by_type = {x["event_type"]: x for x in items}
    assert set(by_type) == {
        "COMMITMENT_PROPOSED",
        "COMMITMENT_CONFIRMED",
        "REPAYMENT_REPORTED",
        "REPAYMENT_VERIFIED" if decision == "verify" else "REPAYMENT_DISPUTED",
    }
    with timeline.api.factory() as db:
        for item in items:
            row = db.get(LedgerEvent, UUID(item["id"]))
            assert item["details"]["status"] == row.event_payload["status"]
            assert item["actor"]["id"] == str(row.actor_user_id)
            if row.terms_version_id:
                assert item["details"]["terms_version_id"] == str(row.terms_version_id)
            if row.repayment_id:
                assert item["details"]["repayment_id"] == str(row.repayment_id)
                assert item["details"]["amount_minor"] == 1000
                assert item["details"]["currency"] == "INR"
    if decision == "verify":
        details = by_type["REPAYMENT_VERIFIED"]["details"]
        assert details["resulting_verified_outstanding_minor"] == 9000
        assert details["resulting_commitment_status"] == "PARTIALLY_REPAID"
    else:
        assert "terms_version_id" not in by_type["REPAYMENT_DISPUTED"]["details"]


@pytest.mark.parametrize(
    "action,actor,status", [("reject", "B", "REJECTED"), ("cancel", "A", "CANCELLED")]
)
def test_rejected_cancelled(timeline, action, actor, status):
    identifier = timeline.request("POST", json=timeline.body).json()["id"]
    assert timeline.request("POST", f"/{identifier}/{action}", actor=actor).status_code == 200
    rows = timeline.timeline(identifier=identifier).json()["items"]
    assert {r["event_type"] for r in rows} == {"COMMITMENT_PROPOSED", "COMMITMENT_" + status}
    assert next(r for r in rows if r["event_type"].endswith(status))["details"] == {
        "status": status
    }


def test_historical_values_not_current_state(timeline):
    assert timeline.decide().status_code == 200
    before = timeline.timeline().json()
    with timeline.api.factory.begin() as db:
        db.get(Commitment, UUID(timeline.identifier)).status = "CLOSED"
    assert timeline.timeline().json() == before


def test_current_actor_names(timeline):
    with timeline.api.factory.begin() as db:
        db.get(User, timeline.users["A"]).display_name = "Renamed"
    assert all(
        x["actor"]["display_name"] == "Renamed"
        for x in timeline.timeline().json()["items"]
        if x["actor"]["id"] == str(timeline.users["A"])
    )


@pytest.mark.parametrize(
    "name",
    [
        "COMMITMENT_PROPOSED",
        "COMMITMENT_CONFIRMED",
        "REPAYMENT_REPORTED",
        "REPAYMENT_VERIFIED",
        "REPAYMENT_DISPUTED",
    ],
)
@pytest.mark.parametrize("payload", [None, [], {}, {"status": "WRONG"}, {"status": 1}])
def test_malformed_payload(timeline, name, payload):
    if name.startswith("REPAYMENT_V"):
        assert timeline.decide().status_code == 200
    elif name == "REPAYMENT_DISPUTED":
        assert timeline.decide("dispute").status_code == 200
    with timeline.api.factory.begin() as db:
        event(db, timeline, name).event_payload = payload
    response = timeline.timeline()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "items" not in response.json()


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_type", "FUTURE_EVENT"),
        ("actor_user_id", None),
        ("terms_version_id", None),
        ("currency", "USD"),
        ("amount_minor", 999),
    ],
)
def test_inconsistent_storage(timeline, field, value):
    with timeline.api.factory.begin() as db:
        setattr(event(db, timeline, "REPAYMENT_REPORTED"), field, value)
    assert timeline.timeline().status_code == 503


@pytest.mark.parametrize("field", ["terms_version_id", "repayment_id", "actor_user_id"])
def test_cross_parent_references(timeline, field):
    other = timeline.commitment()
    report = timeline.report(parent=other)
    assert report.status_code == 201
    with timeline.api.factory.begin() as db:
        other_event = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.commitment_id == UUID(other),
                LedgerEvent.event_type == "REPAYMENT_REPORTED",
            )
        )
        value = timeline.users["C"] if field == "actor_user_id" else getattr(other_event, field)
        setattr(event(db, timeline, "REPAYMENT_REPORTED"), field, value)
    result = timeline.timeline()
    assert result.status_code == 503
    assert str(value) not in result.text


def test_cross_repayment_verification(timeline):
    assert timeline.decide().status_code == 200
    second = timeline.report().json()["id"]
    assert timeline.decide(identifier=second).status_code == 200
    with timeline.api.factory.begin() as db:
        rows = list(
            db.scalars(
                select(LedgerEvent).where(
                    LedgerEvent.commitment_id == UUID(timeline.identifier),
                    LedgerEvent.event_type == "REPAYMENT_VERIFIED",
                )
            )
        )
        rows[0].event_payload = rows[1].event_payload.copy()
    assert timeline.timeline().status_code == 503


@pytest.mark.parametrize("value", [True, "9000", -1, None, 1.5])
def test_historical_amount_strict(timeline, value):
    assert timeline.decide().status_code == 200
    with timeline.api.factory.begin() as db:
        row = event(db, timeline, "REPAYMENT_VERIFIED")
        row.event_payload = {**row.event_payload, "verified_outstanding": value}
    assert timeline.timeline().status_code == 503


@pytest.mark.parametrize("value", ["invalid", str(uuid4()), None, 42])
def test_bad_verification_reference(timeline, value):
    assert timeline.decide().status_code == 200
    with timeline.api.factory.begin() as db:
        row = event(db, timeline, "REPAYMENT_VERIFIED")
        row.event_payload = {**row.event_payload, "verification_id": value}
    assert timeline.timeline().status_code == 503


@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
def test_currency_full_repayment_projection(timeline, currency):
    parent = timeline.commitment(currency=currency)
    report = timeline.report(parent=parent, amount_minor=10000, currency=currency)
    assert report.status_code == 201
    assert timeline.decide(identifier=report.json()["id"]).status_code == 200
    items = timeline.timeline(identifier=parent).json()["items"]
    verified = next(x for x in items if x["event_type"] == "REPAYMENT_VERIFIED")
    assert verified["details"]["amount_minor"] == 10000
    assert verified["details"]["currency"] == currency
    assert verified["details"]["resulting_verified_outstanding_minor"] == 0
    assert verified["details"]["resulting_commitment_status"] == "FULLY_REPAID"


def test_historical_terms_provenance_and_later_repayment(timeline):
    from terms.test_versions import version

    initial = next(
        x for x in timeline.timeline().json()["items"] if x["event_type"] == "COMMITMENT_PROPOSED"
    )["details"]["terms_version_id"]
    current = version(timeline, timeline.identifier, 2, timeline.api.clock.now)
    assert timeline.decide().status_code == 200
    before = timeline.timeline().json()["items"]
    for row in before:
        if row["event_type"] in ("COMMITMENT_PROPOSED", "REPAYMENT_REPORTED"):
            assert row["details"]["terms_version_id"] == initial
        elif row["event_type"] == "REPAYMENT_VERIFIED":
            assert row["details"]["terms_version_id"] == current
    version(timeline, timeline.identifier, 3, timeline.api.clock.now)
    second = timeline.report().json()["id"]
    assert timeline.decide(identifier=second).status_code == 200
    after = {x["id"]: x for x in timeline.timeline().json()["items"]}
    assert all(after[x["id"]] == x for x in before)
