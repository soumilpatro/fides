from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from app.models.auth_session import AuthSession
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.connection import Connection
from app.models.extension_request import ExtensionRequest
from app.models.idempotency_key import IdempotencyKey
from app.models.ledger_event import LedgerEvent
from app.models.repayment import Repayment
from sqlalchemy import event, select

from .helpers import assert_effects, snapshot


def serialized(env, first, second, model, hook="before_insert"):
    """First holds authoritative locks; observe the second trying a User lock.

    Events enforce both overlap and ordering, rather than relying on timing sleeps.
    Futures and cleanup are bounded even when an assertion fails.
    """
    entered, release, waiting = Event(), Event(), Event()
    engine = env.api.factory.kw["bind"]

    def hold(*args):
        if not entered.is_set():
            entered.set()
            assert release.wait(15)

    def observe(conn, cursor, sql, parameters, context, many):
        if entered.is_set() and "FROM users" in sql and "FOR UPDATE" in sql:
            waiting.set()

    event.listen(model, hook, hold)
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(2) as pool:
            winner = pool.submit(first)
            try:
                assert entered.wait(10)
                follower = pool.submit(second)
                assert waiting.wait(10)
                assert not follower.done()
            finally:
                release.set()
            return winner.result(20), follower.result(20)
    finally:
        release.set()
        event.remove(model, hook, hold)
        event.remove(engine, "before_cursor_execute", observe)


def test_reject_vs_reject_complete_effects(ctx):
    proposed = ctx.request("POST", json=ctx.body).json()["id"]
    before = snapshot(ctx)
    first, second = serialized(
        ctx,
        lambda: ctx.request("POST", f"/{proposed}/reject", actor="B", key="reject-one"),
        lambda: ctx.request("POST", f"/{proposed}/reject", actor="B", key="reject-two"),
        Commitment,
        "before_update",
    )
    assert first.status_code == 200 and first.json()["status"] == "REJECTED"
    assert second.status_code == 409 and second.json()["error"]["code"] == "INVALID_STATE"
    assert_effects(before, snapshot(ctx), "reject")


def test_reversed_participant_proposals_serialize(ctx):
    before = snapshot(ctx)
    results = serialized(
        ctx,
        lambda: ctx.request("POST", json=ctx.body),
        lambda: ctx.request("POST", actor="B", json=ctx.body),
        Commitment,
    )
    assert [r.status_code for r in results] == [201, 201]
    a, b = (r.json() for r in results)
    assert a["borrower"]["id"] == b["lender"]["id"]
    assert a["lender"]["id"] == b["borrower"]["id"]
    after = snapshot(ctx)
    for name in before:
        assert len(after[name]) - len(before[name]) == (
            2
            if name
            in {
                "Commitment",
                "CommitmentTermsVersion",
                "LedgerEvent",
                "AuditLog",
                "NotificationEvent",
                "IdempotencyKey",
            }
            else 0
        )


@pytest.mark.parametrize("report_actor", ["A", "B"])
@pytest.mark.parametrize("verify_first", [True, False])
def test_reporting_vs_verification_cross_route(b8, report_actor, verify_first):
    from app.models.repayment_verification import RepaymentVerification

    before = snapshot(b8)

    def report():
        return b8.report(actor=report_actor)

    verify = b8.decide
    first, second = serialized(
        b8,
        verify if verify_first else report,
        report if verify_first else verify,
        RepaymentVerification if verify_first else Repayment,
    )
    assert [r.status_code for r in (first, second)] == ([200, 201] if verify_first else [201, 200])
    after = snapshot(b8)
    for name in before:
        addition = (
            2
            if name in {"LedgerEvent", "AuditLog", "NotificationEvent", "IdempotencyKey"}
            else (1 if name in {"Repayment", "RepaymentVerification"} else 0)
        )
        assert len(after[name]) - len(before[name]) == addition, name
    with b8.api.factory() as db:
        assert db.get(Commitment, UUID(b8.identifier)).status == "PARTIALLY_REPAID"


def test_extension_accept_vs_new_proposal(b10):
    requested = b10.create().json()["id"]
    before = snapshot(b10)
    accepted, proposed = serialized(
        b10,
        lambda: b10.decide(requested),
        lambda: b10.create(actor="B", requested_due_date="2026-12-10"),
        CommitmentTermsVersion,
    )
    assert accepted.status_code == 200 and proposed.status_code == 201
    with b10.api.factory() as db:
        rows = list(
            db.scalars(
                select(ExtensionRequest).where(
                    ExtensionRequest.commitment_id == UUID(b10.identifier)
                )
            )
        )
        assert sum(r.status == "REQUESTED" for r in rows) == 1
        new = next(r for r in rows if r.status == "REQUESTED")
        version = db.get(CommitmentTermsVersion, UUID(new.requested_terms["base_terms_version_id"]))
        assert version.version_no == 2
    after = snapshot(b10)
    assert len(after["CommitmentTermsVersion"]) == len(before["CommitmentTermsVersion"]) + 1
    for name in ("LedgerEvent", "AuditLog", "NotificationEvent", "IdempotencyKey"):
        assert len(after[name]) == len(before[name]) + 2


@pytest.mark.parametrize("accept_first", [True, False])
def test_extension_accept_vs_report_uses_effective_terms(b10, accept_first):
    requested = b10.create().json()["id"]
    before = snapshot(b10)

    def accept():
        return b10.decide(requested)

    def report():
        return b10.report(parent=b10.identifier, amount_minor=10500)

    first, second = serialized(
        b10,
        accept if accept_first else report,
        report if accept_first else accept,
        CommitmentTermsVersion if accept_first else Repayment,
    )
    assert (first.status_code, second.status_code) == ((200, 201) if accept_first else (201, 200))
    with b10.api.factory() as db:
        posting = db.scalar(
            select(LedgerEvent).where(
                LedgerEvent.commitment_id == UUID(b10.identifier),
                LedgerEvent.event_type == "REPAYMENT_REPORTED",
            )
        )
        assert db.get(CommitmentTermsVersion, posting.terms_version_id).version_no == (
            2 if accept_first else 1
        )
    assert (
        b10.report(parent=b10.identifier, amount_minor=1).json()["error"]["code"]
        == "OVER_REPAYMENT"
    )
    after = snapshot(b10)
    assert len(after["Repayment"]) == len(before["Repayment"]) + 1
    assert len(after["CommitmentTermsVersion"]) == len(before["CommitmentTermsVersion"]) + 1
    for name in ("LedgerEvent", "AuditLog", "NotificationEvent", "IdempotencyKey"):
        assert len(after[name]) == len(before[name]) + 2


@pytest.mark.parametrize("credential_action", ["logout", "refresh"])
@pytest.mark.parametrize("credential_first", [True, False])
def test_financial_request_vs_credentials(b10, credential_action, credential_first):
    credentials = b10.api.service.create(b10.users["A"], intent="login")
    b10.headers["A"]["Authorization"] = "Bearer " + credentials.access_token
    before = snapshot(b10)

    def credential():
        return b10.api.client.post(
            f"/api/v1/auth/{credential_action}",
            headers=b10.headers["A"],
            json={"refresh_token": credentials.refresh_token}
            if credential_action == "refresh"
            else {},
        )

    def report():
        return b10.report(parent=b10.identifier, key="credential-race")

    a, b = serialized(
        b10,
        credential if credential_first else report,
        report if credential_first else credential,
        AuthSession if credential_first else Repayment,
        "before_update" if credential_first else "before_insert",
    )
    auth, financial = (a, b) if credential_first else (b, a)
    assert auth.status_code == 200
    assert financial.status_code == (401 if credential_first else 201)
    after = snapshot(b10)
    for name in before:
        expected = (1 if name == "AuditLog" else 0) + (
            0
            if credential_first
            else 1
            if name
            in {"Repayment", "LedgerEvent", "AuditLog", "NotificationEvent", "IdempotencyKey"}
            else 0
        )
        assert len(after[name]) - len(before[name]) == expected, name
    if credential_first:
        assert financial.json()["error"]["code"] == (
            "SESSION_REVOKED" if credential_action == "logout" else "INVALID_AUTH_TOKEN"
        )


@pytest.mark.parametrize("action", ["block", "remove"])
@pytest.mark.parametrize("connection_first", [True, False])
def test_connection_vs_confirmation(ctx, action, connection_first):
    proposed = ctx.request("POST", json=ctx.body).json()["id"]
    before = snapshot(ctx)

    def confirm():
        return ctx.request("POST", f"/{proposed}/confirm", actor="B", key="confirm-race")

    def transition():
        return ctx.call(
            "DELETE" if action == "remove" else "POST",
            f"/{ctx.connection}" + ("/block" if action == "block" else ""),
        )

    a, b = serialized(
        ctx,
        transition if connection_first else confirm,
        confirm if connection_first else transition,
        Connection if connection_first else Commitment,
        "before_update",
    )
    connection, financial = (a, b) if connection_first else (b, a)
    assert connection.status_code == 200
    assert financial.status_code == (409 if connection_first else 200)
    assert ctx.request("GET", f"/{proposed}", actor="A").status_code == 200
    assert ctx.request("GET", f"/{proposed}", actor="B").status_code == 200
    after = snapshot(ctx)
    for name in before:
        expected = (1 if name == "AuditLog" else 0) + (
            0
            if connection_first
            else 1
            if name in {"LedgerEvent", "AuditLog", "NotificationEvent", "IdempotencyKey"}
            else 0
        )
        assert len(after[name]) - len(before[name]) == expected, name
    with ctx.api.factory() as db:
        assert db.get(Commitment, UUID(proposed)).status == (
            "PENDING_CONFIRMATION" if connection_first else "ACTIVE"
        )
        assert (
            db.scalar(
                select(IdempotencyKey.id).where(IdempotencyKey.idempotency_key == "confirm-race")
            )
            is None
            if connection_first
            else True
        )
