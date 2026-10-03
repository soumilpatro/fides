from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.models.commitment import Commitment
from app.models.enums import CommitmentStatus
from app.models.mutual_closure_request import MutualClosureRequest
from app.models.repayment import Repayment
from app.models.repayment_verification import RepaymentVerification
from app.models.user import User
from sqlalchemy import delete, func, select

from verification.conftest import seed

from .conftest import error, requested


@pytest.mark.parametrize("actor,other", [("A", "B"), ("B", "A")])
@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
def test_derived_proposal(mc, actor, other, currency):
    parent = mc.identifier if currency == "INR" else mc.commitment(currency=currency)
    result = mc.create(actor=actor, parent=parent, note="  private agreement  ")
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["requested_by"]["id"] == str(mc.users[actor])
    assert body["counterparty"]["id"] == str(mc.users[other])
    assert body["currency"] == currency
    assert body["outstanding_snapshot_minor"] == body["waived_amount_minor"] == 10000
    assert body["note"] == "private agreement"
    assert body["decided_by"] is body["decided_at"] is None
    assert body["created_at"] == body["updated_at"]


@pytest.mark.parametrize(
    "status", [s.value for s in CommitmentStatus if s.value not in ("ACTIVE", "PARTIALLY_REPAID")]
)
def test_ineligible_create(mc, status):
    with mc.api.factory.begin() as db:
        db.get(Commitment, UUID(mc.identifier)).status = status
    error(mc.create(), "INVALID_STATE")


def test_zero_outstanding(mc):
    seed(mc, 10000, "VERIFIED")
    error(mc.create(), "INVALID_STATE")


@pytest.mark.parametrize(
    "status", [s.value for s in CommitmentStatus if s.value not in ("ACTIVE", "PARTIALLY_REPAID")]
)
def test_ineligible_accept(mc, status):
    identifier = requested(mc)
    with mc.api.factory.begin() as db:
        db.get(Commitment, UUID(mc.identifier)).status = status
    error(mc.decide(identifier), "INVALID_STATE")
    assert mc.closure_read(identifier=identifier).json()["status"] == "REQUESTED"


def test_zero_outstanding_accept(mc):
    identifier = requested(mc)
    seed(mc, 10000, "VERIFIED")
    error(mc.decide(identifier), "INVALID_STATE")


@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
def test_current_terms_interest_snapshot(mc, currency):
    parent = mc.commitment(
        currency=currency, terms={"interest_type": "SIMPLE_FIXED", "interest_rate_bps": 500}
    )
    result = mc.create(parent=parent)
    assert result.status_code == 201
    assert (
        result.json()["outstanding_snapshot_minor"] == result.json()["waived_amount_minor"] == 10500
    )
    assert mc.decide(result.json()["id"]).status_code == 200


@pytest.mark.parametrize("action", ["create", "accept", "cancel"])
def test_inactive_other_party(mc, action):
    identifier = requested(mc) if action != "create" else None
    with mc.api.factory.begin() as db:
        db.get(
            User, mc.users["B" if action in ("create", "cancel") else "A"]
        ).status = "DEACTIVATED"
    response = (
        mc.create()
        if action == "create"
        else mc.decide(identifier, action, actor="A" if action == "cancel" else "B")
    )
    if action == "cancel":
        assert response.status_code == 200
    else:
        error(response, "SERVICE_UNAVAILABLE", 503)


def test_pending_does_not_reduce_proposal_snapshot(mc):
    assert mc.report(amount_minor=9000).status_code == 201
    result = mc.create()
    assert result.status_code == 201
    assert result.json()["outstanding_snapshot_minor"] == 10000
    error(mc.decide(result.json()["id"]), "CONFLICT")
    assert mc.closure_read().json()[0]["status"] == "REQUESTED"


@pytest.mark.parametrize("status", ["VERIFIED", "DISPUTED", "CANCELLED"])
def test_accounting_statuses(mc, status):
    seed(mc, 1000, status)
    result = mc.create()
    expected = 9000 if status == "VERIFIED" else 10000
    assert result.json()["outstanding_snapshot_minor"] == expected
    assert mc.decide(result.json()["id"]).status_code == 200
    with mc.api.factory() as db:
        assert db.get(Commitment, UUID(mc.identifier)).status == "CLOSED"
        assert (
            db.scalar(
                select(func.count())
                .select_from(Repayment)
                .where(Repayment.commitment_id == UUID(mc.identifier))
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(RepaymentVerification)) >= (
            status != "CANCELLED"
        )


def test_snapshot_mismatch_and_fresh_proposal(mc):
    identifier = requested(mc)
    report = mc.report(amount_minor=1000).json()["id"]
    assert mc.verify(report).status_code == 200
    error(mc.decide(identifier), "CONFLICT")
    row = mc.closure_read(identifier=identifier).json()
    assert row["status"] == "REQUESTED" and row["waived_amount_minor"] == 10000
    assert mc.decide(identifier, "cancel", actor="A").status_code == 200
    fresh = requested(mc)
    assert mc.decide(fresh).json()["waived_amount_minor"] == 9000


@pytest.mark.parametrize("action", ["accept", "reject", "cancel"])
@pytest.mark.parametrize("requester", ["A", "B"])
def test_roles_and_terminal_decisions(mc, action, requester):
    other = "B" if requester == "A" else "A"
    actor = requester if action == "cancel" else other
    wrong = other if action == "cancel" else requester
    identifier = requested(mc, actor=requester)
    error(mc.decide(identifier, action, actor=wrong), "FORBIDDEN", 403)
    mc.api.clock.now += timedelta(seconds=1)
    result = mc.decide(identifier, action, actor=actor)
    assert result.status_code == 200, result.text
    assert (
        result.json()["status"]
        == {"accept": "ACCEPTED", "reject": "REJECTED", "cancel": "CANCELLED"}[action]
    )
    assert result.json()["decided_by"]["id"] == str(mc.users[actor])
    assert result.json()["updated_at"] == result.json()["decided_at"]
    error(mc.decide(identifier, action, actor=actor), "INVALID_STATE")
    with mc.api.factory() as db:
        assert db.get(Commitment, UUID(mc.identifier)).status == (
            "CLOSED" if action == "accept" else "ACTIVE"
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Repayment)
                .where(Repayment.commitment_id == UUID(mc.identifier))
            )
            == 0
        )


@pytest.mark.parametrize("action", ["reject", "cancel"])
@pytest.mark.parametrize("state", ["FULLY_REPAID", "CLOSED", "CANCELLED", "REJECTED"])
def test_stale_request_resolution(mc, action, state):
    identifier = requested(mc)
    with mc.api.factory.begin() as db:
        db.get(Commitment, UUID(mc.identifier)).status = state
    result = mc.decide(identifier, action, actor="A" if action == "cancel" else "B")
    assert result.status_code == 200, result.text
    with mc.api.factory() as db:
        assert db.get(Commitment, UUID(mc.identifier)).status == state


@pytest.mark.parametrize("action", ["accept", "reject", "cancel", "detail", "list", "create"])
@pytest.mark.parametrize("missing", [False, True])
def test_idor_and_missing(mc, action, missing):
    identifier = str(uuid4()) if missing else requested(mc)
    parent = str(uuid4()) if missing else mc.identifier
    if action == "create":
        response = mc.create(actor="C", parent=parent)
    elif action in ("detail", "list"):
        response = mc.closure_read(
            actor="C", identifier=identifier if action == "detail" else None, parent=parent
        )
    else:
        response = mc.decide(identifier, action, actor="C")
    error(response, "NOT_FOUND", 404)
    assert response.json()["error"]["message"] == "Unavailable resource."


def test_unique_pending_and_history_order(mc):
    first = requested(mc)
    error(mc.create(actor="B"), "CONFLICT")
    assert mc.decide(first, "cancel", actor="A").status_code == 200
    second = requested(mc, actor="B")
    rows = mc.closure_read().json()
    assert [r["id"] for r in rows] == sorted([first, second])
    with mc.api.factory.begin() as db:
        row = db.get(MutualClosureRequest, UUID(second))
        row.created_at += timedelta(seconds=1)
        row.updated_at = row.created_at
    assert mc.closure_read().json()[0]["id"] == second
    for actor in "AB":
        assert mc.closure_read(actor=actor, identifier=first).status_code == 200


@pytest.mark.parametrize(
    "damage", ["missing_history", "wrong_actor", "wrong_currency", "bad_parties"]
)
def test_corrupt_provenance_fails_closed(mc, damage):
    identifier = requested(mc)
    report = seed(mc, 1000, "VERIFIED")
    with mc.api.factory.begin() as db:
        if damage == "missing_history":
            db.execute(
                delete(RepaymentVerification).where(RepaymentVerification.repayment_id == report)
            )
        elif damage == "wrong_actor":
            db.scalar(
                select(RepaymentVerification).where(RepaymentVerification.repayment_id == report)
            ).decided_by_user_id = mc.users["A"]
        elif damage == "wrong_currency":
            db.get(MutualClosureRequest, UUID(identifier)).currency = "USD"
        else:
            db.get(MutualClosureRequest, UUID(identifier)).counterparty_user_id = mc.users["C"]
    error(mc.decide(identifier), "SERVICE_UNAVAILABLE", 503)
    with mc.api.factory() as db:
        assert db.get(MutualClosureRequest, UUID(identifier)).status == "REQUESTED"
        assert db.get(Commitment, UUID(mc.identifier)).status == "ACTIVE"
