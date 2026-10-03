import logging
from types import SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4

import pytest
from app.api.auth import get_auth_service
from app.api.dependencies import require_principal
from app.auth.sessions import Principal
from app.core.errors import AuthError, ResourceUnavailable
from app.main import create_app
from app.models.commitment import Commitment
from app.models.enums import UserStatus
from app.models.user import User
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from .test_authorization import KINDS, lookup


@pytest.fixture
def http(graph):
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: SimpleNamespace(
        session_service=graph.service
    )

    # Test-only integration harness, never registered on the production app.
    @app.get("/test/authorization/{kind}/{resource_id}")
    def protected(
        kind: Literal[
            "connection",
            "commitment",
            "repayment",
            "verification",
            "ledger_event",
            "extension_request",
        ],
        resource_id: UUID,
        principal: Principal = Depends(require_principal),
    ):
        with graph.factory.begin() as db:
            return getattr(graph.authorization, kind)(db, principal, resource_id)

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("kind", ["connection", *KINDS])
def test_idor_http_is_indistinguishable_from_missing_and_leaks_no_content(graph, http, kind):
    actor = "C" if kind == "connection" else "B"
    existing = graph.connection_ab if kind == "connection" else graph.groups[0][kind]
    responses = [
        http.get(
            f"/test/authorization/{kind}/{identifier}",
            headers={
                "Authorization": "Bearer " + graph.credentials[actor].access_token,
                "X-Request-ID": "safe-correlation",
            },
        )
        for identifier in (existing, uuid4())
    ]
    assert all(response.status_code == 404 for response in responses)
    assert (
        responses[0].json()
        == responses[1].json()
        == {"error": {"code": "NOT_FOUND", "message": "Unavailable resource."}}
    )
    for response in responses:
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Request-ID"] == "safe-correlation"
        assert all(
            secret not in response.text
            for secret in ("Private", "918273", "12345", str(existing), str(graph.users["A"]))
        )


def test_http_b2_principal_is_only_authority_and_ordinary_auth_is_required(graph, http):
    path = f'/test/authorization/commitment/{graph.groups[0]["commitment"]}'
    assert http.get(path).json()["error"]["code"] == "AUTH_REQUIRED"
    response = http.get(
        path + f'?actor_user_id={graph.users["A"]}&role=lender&owner=true',
        headers={"Authorization": "Bearer " + graph.credentials["B"].access_token},
    )
    assert response.status_code == 404
    response = http.get(
        path, headers={"Authorization": "Bearer " + graph.credentials["C"].access_token}
    )
    assert response.status_code == 200 and response.json()["role"] == "borrower"


def test_b2_surface_unchanged_with_b4_connections():
    schema = create_app().openapi()
    operations = {
        (method, path)
        for path, item in schema["paths"].items()
        if path.startswith("/api/v1/")
        and not path.startswith(
            (
                "/api/v1/connections",
                "/api/v1/commitments",
                "/api/v1/repayments",
                "/api/v1/extension-requests",
                "/api/v1/closure-requests",
                "/api/v1/notifications",
                "/api/v1/notification-preferences",
                "/api/v1/summary",
            )
        )
        for method in item
    }
    assert operations == {
        ("post", "/api/v1/auth/" + suffix)
        for suffix in ("otp/request", "otp/verify", "refresh", "logout")
    } | {("get", "/api/v1/me"), ("patch", "/api/v1/me"), ("post", "/api/v1/me/deactivate")}


def test_cached_orm_state_cannot_restore_inactive_actor(graph):
    with graph.factory.begin() as db:
        cached = db.get(User, graph.users["A"])
        assert cached.status == UserStatus.ACTIVE
        with graph.factory.begin() as writer:
            writer.get(User, graph.users["A"]).status = UserStatus.DEACTIVATED
        with pytest.raises(AuthError, match="ACCOUNT_DEACTIVATED"):
            graph.authorization.commitment(db, graph.principals["A"], graph.groups[0]["commitment"])


def test_cached_commitment_cannot_override_authoritative_membership(graph):
    with graph.factory.begin() as db:
        cached = db.get(Commitment, graph.groups[0]["commitment"])
        with graph.factory.begin() as writer:
            writer.get(Commitment, cached.id).borrower_user_id = graph.users["B"]
        with pytest.raises(ResourceUnavailable):
            graph.authorization.commitment(db, graph.principals["C"], cached.id)


def test_dirty_caller_object_is_not_flushed_or_trusted(graph):
    with graph.factory.begin() as db:
        db.autoflush = True
        row = db.get(Commitment, graph.groups[0]["commitment"])
        row.borrower_user_id = graph.users["B"]
        with pytest.raises(ValueError, match="Authorize before staging mutations"):
            graph.authorization.commitment(db, graph.principals["B"], row.id)
        db.rollback()
    with pytest.raises(ResourceUnavailable):
        lookup(graph, "commitment", "B")


@pytest.mark.parametrize("kind", KINDS)
def test_financial_lookup_uses_one_filtered_join_without_values_or_histories(graph, kind):
    queries = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "FROM" in statement:
            queries.append(statement)

    engine = graph.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        lookup(graph, kind, "A")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    # Two B2 current-principal queries, then one resource query, independent of history size.
    assert len(queries) == 3
    financial = queries[-1]
    assert "lender_user_id" in financial and "borrower_user_id" in financial
    assert all(
        field not in financial
        for field in (
            "amount_minor",
            "description",
            "note",
            "event_payload",
            "reason",
            "connections",
        )
    )


def test_database_failure_maps_safely_and_logs_hide_financial_data(graph, caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("sqlalchemy.engine.Engine"), "disabled", False)
    logging.getLogger().addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger="sqlalchemy.engine")
    lookup(graph, "verification", "A")
    assert "Authentication I/O diagnostic redacted" in caplog.text

    def fail(connection, cursor, statement, parameters, context, executemany):
        if "FROM commitments" in statement:
            raise SQLAlchemyError("Private financial diagnostic 918273")

    engine = graph.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(AuthError, match="SERVICE_UNAVAILABLE"):
            lookup(graph, "commitment", "A")
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert all(
        secret not in caplog.text
        for secret in ("Private", "918273", graph.credentials["A"].access_token)
    )


@pytest.mark.parametrize(
    "kind,child",
    [
        ("repayment", "repayments"),
        ("verification", "repayments"),
        ("extension_request", "extension_requests"),
        ("ledger_event", None),
    ],
)
def test_write_lock_order_is_user_commitment_then_mutable_child(graph, kind, child):
    locks = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement:
            locks.append(statement)

    engine = graph.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        lookup(graph, kind, "A", lock=True)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(locks) == (3 if child else 2)
    assert "FROM users" in locks[0] and "FROM commitments" in locks[1]
    if child:
        assert "FROM " + child in locks[2]


def test_write_mode_rechecks_child_parent_after_lock_wait(graph):
    from app.models.repayment import Repayment

    switched = []

    def change_parent(connection, cursor, statement, parameters, context, executemany):
        if "FROM commitments" in statement and "FOR UPDATE" in statement and not switched:
            switched.append(True)
            # Simulate an authoritative relationship change before the parent lock.
            # Both targets have A/C participants, so membership alone is insufficient:
            # the new parent must not be returned while only the old parent is locked.
            with graph.factory.begin() as writer:
                writer.get(Repayment, graph.groups[0]["repayment"]).commitment_id = graph.groups[1][
                    "commitment"
                ]

    engine = graph.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", change_parent)
    try:
        with pytest.raises(ResourceUnavailable):
            lookup(graph, "repayment", "A", lock=True)
    finally:
        event.remove(engine, "before_cursor_execute", change_parent)
    assert switched == [True]
