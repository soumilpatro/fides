from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest
from app.api.summary import get_occurrence_service
from app.api.summary_schemas import OccurrenceResponse
from app.main import create_app
from app.models.auth_session import AuthSession
from app.models.user import User
from pydantic import ValidationError
from reliability.helpers import snapshot
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .conftest import items

FIELDS = {
    "commitment_id",
    "counterparty",
    "role",
    "currency",
    "verified_outstanding_minor",
    "due_date",
    "due_timezone",
    "schedule_mode",
    "installment_id",
}


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
def test_exact_private_read_only_contract(occ, kind):
    occ.configure(due="2026-09-10" if kind == "overdue" else "2026-09-11")
    before = snapshot(occ)
    response = occ.query(kind)
    assert set(response.json()) == {"items", "next_cursor"}
    row = items(response)[0]
    assert set(row) == FIELDS and set(row["counterparty"]) == {"id", "display_name"}
    assert row["installment_id"] is None and type(row["verified_outstanding_minor"]) is int
    assert all(phone not in response.text for phone in occ.phones.values())
    assert snapshot(occ) == before
    assert items(occ.query(kind, "C")) == []


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize(
    "state,code,status",
    [
        ("missing", "AUTH_REQUIRED", 401),
        ("invalid", "INVALID_AUTH_TOKEN", 401),
        ("expired", "AUTH_TOKEN_EXPIRED", 401),
        ("revoked", "SESSION_REVOKED", 401),
        ("inactive", "ACCOUNT_DEACTIVATED", 403),
    ],
)
def test_authentication(occ, kind, state, code, status):
    headers = dict(occ.headers["A"])
    if state == "missing":
        headers = {}
    elif state == "invalid":
        headers = {"Authorization": "Bearer invalid"}
    else:
        with occ.api.factory.begin() as db:
            session = db.scalar(select(AuthSession).where(AuthSession.user_id == occ.users["A"]))
            if state == "expired":
                occ.api.clock.now = session.access_expires_at + timedelta(seconds=1)
            if state == "revoked":
                session.revoked_at = occ.api.clock.now
                session.revocation_reason = "LOGOUT"
            if state == "inactive":
                db.get(User, occ.users["A"]).status = "DEACTIVATED"
    response = occ.api.client.get("/api/v1/summary/" + kind, headers=headers)
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert response.headers["Cache-Control"] == "no-store"
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize(
    "path",
    ["success", "validation", "unauthorized", "oversize", "database", "unexpected"],
)
def test_b14_headers_and_raw_path(occ, monkeypatch, kind, path):
    kwargs = {
        "headers": {
            **occ.headers["A"],
            "Host": "[malformed",
            "X-Request-ID": "unsafe request id",
        }
    }
    expected = 200
    if path == "validation":
        kwargs["params"] = {"limit": 0}
        expected = 422
    if path == "unauthorized":
        kwargs["headers"].pop("Authorization")
        expected = 401
    if path == "oversize":
        kwargs["content"] = b"x" * (1048576 + 1)
        expected = 413
    if path == "database":

        def broken(*args):
            raise SQLAlchemyError("secret database internals")

        monkeypatch.setattr(occ.api.challenges.session_service, "revalidate_user_locked", broken)
        expected = 503
    if path == "unexpected":

        class Broken:
            def list(self, *args):
                raise RuntimeError("secret internals")

        occ.api.app.dependency_overrides[get_occurrence_service] = lambda: Broken()
        expected = 500
    response = occ.api.client.request("GET", "/api/v1/summary/" + kind, **kwargs)
    assert response.status_code == expected, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Request-ID"] != "unsafe request id"
    assert "secret" not in response.text


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
@pytest.mark.parametrize("body", ["{}", "null", "[]", "{"])
def test_no_body(occ, kind, body):
    result = occ.api.client.request(
        "GET", "/api/v1/summary/" + kind, headers=occ.headers["A"], content=body
    )
    assert result.status_code == 422


def test_openapi_exact_routes_schemas():
    spec = create_app().openapi()
    for kind in ("upcoming", "overdue"):
        path = spec["paths"]["/api/v1/summary/" + kind]
        assert set(path) == {"get"}
        op = path["get"]
        assert op["security"] == [{"HTTPBearer": []}] and "requestBody" not in op
        assert {p["name"] for p in op["parameters"]} == {"limit", "cursor"}
        limit = next(p["schema"] for p in op["parameters"] if p["name"] == "limit")
        assert limit["default"] == 50 and limit["minimum"] == 1 and limit["maximum"] == 100
        assert set(op["responses"]) == {
            "200",
            "400",
            "401",
            "403",
            "413",
            "422",
            "500",
            "503",
        }
        assert op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/OccurrenceResponse"
        )
    schemas = spec["components"]["schemas"]
    for name, fields in (
        ("OccurrenceItem", FIELDS),
        ("OccurrenceResponse", {"items", "next_cursor"}),
    ):
        schema = schemas[name]
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == set(schema["required"]) == fields


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "phone",
        "null_amount",
        "string_amount",
        "bool_amount",
        "zero_amount",
        "large_amount",
        "role",
        "currency",
        "timezone",
        "mode",
        "missing_cursor",
    ],
)
def test_closed_schema(occ, change):
    value = deepcopy(occ.query().json())
    row = value["items"][0]
    if change == "extra":
        value["totals"] = 1
    if change == "phone":
        row["counterparty"]["phone"] = "private"
    if change == "null_amount":
        row["verified_outstanding_minor"] = None
    if change == "string_amount":
        row["verified_outstanding_minor"] = "10000"
    if change == "bool_amount":
        row["verified_outstanding_minor"] = True
    if change == "zero_amount":
        row["verified_outstanding_minor"] = 0
    if change == "large_amount":
        row["verified_outstanding_minor"] = 2**53
    if change == "role":
        row["role"] = "ADMIN"
    if change == "currency":
        row["currency"] = "EUR"
    if change == "timezone":
        row["due_timezone"] = "invalid"
    if change == "mode":
        row["schedule_mode"] = "none"
    if change == "missing_cursor":
        value.pop("next_cursor")
    with pytest.raises(ValidationError):
        OccurrenceResponse.model_validate(value)


@pytest.mark.parametrize("status", ["BLOCKED", "REMOVED"])
def test_connection_and_counterparty_status_do_not_remove_financial_visibility(occ, status):
    from app.models.connection import Connection

    with occ.api.factory.begin() as db:
        db.get(Connection, UUID(occ.connection)).status = status
        db.get(User, occ.users["B"]).status = "DEACTIVATED"
    assert len(items(occ.query())) == 1


def test_preferences_do_not_filter_queries(occ):
    result = occ.api.client.post(
        "/api/v1/notification-preferences",
        headers=occ.headers["A"],
        json={"due_reminders_enabled": False, "overdue_reminders_enabled": False},
    )
    assert result.status_code == 200, result.text
    assert items(occ.query())


def test_mutual_closure_removes_occurrence_preserves_history(occ):
    closure = occ.create().json()["id"]
    assert occ.decide(closure).status_code == 200
    assert items(occ.query()) == [] and items(occ.query("overdue")) == []
    assert occ.timeline().status_code == 200
