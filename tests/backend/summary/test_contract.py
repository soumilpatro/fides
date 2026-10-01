from copy import deepcopy
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.summary import get_summary_service
from app.api.summary_schemas import MAX_SAFE_INTEGER, SummaryResponse
from app.main import create_app
from app.models.auth_session import AuthSession
from app.models.user import User
from .conftest import read

ZERO = {
    "currencies": [
        {
            "currency": c,
            "borrowed_outstanding_minor": 0,
            "lent_outstanding_minor": 0,
            "net_position_minor": 0,
        }
        for c in ("INR", "USD", "GBP")
    ]
}


def test_empty_account(ctx):
    response = read(ctx)
    assert response.status_code == 200
    assert response.json() == ZERO
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "query",
    [
        "user_id=other",
        "currency=USD",
        "limit=1",
        "cursor=x",
        "upcoming=true",
        "overdue=true",
        "foo=",
        "foo=1&foo=2",
        "=x",
    ],
)
def test_queries_rejected(ctx, query):
    result = ctx.api.client.get("/api/v1/summary?" + query, headers=ctx.headers["A"])
    assert result.status_code == 422
    assert result.json() == {
        "error": {"code": "VALIDATION_ERROR", "message": "Request validation failed."}
    }


@pytest.mark.parametrize("body", ["{}", "null", "[]", "{", "1"])
def test_body_not_supported(ctx, body):
    result = ctx.api.client.request(
        "GET", "/api/v1/summary", headers=ctx.headers["A"], content=body
    )
    assert result.status_code == 422


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("missing", "AUTH_REQUIRED"),
        ("invalid", "INVALID_AUTH_TOKEN"),
        ("expired", "AUTH_TOKEN_EXPIRED"),
        ("revoked", "SESSION_REVOKED"),
        ("inactive", "ACCOUNT_DEACTIVATED"),
    ],
)
def test_authentication(ctx, kind, expected):
    headers = ctx.headers["A"]
    if kind == "missing":
        headers = {}
    elif kind == "invalid":
        headers = {"Authorization": "Bearer invalid"}
    else:
        with ctx.api.factory.begin() as db:
            session = db.scalar(select(AuthSession).where(AuthSession.user_id == ctx.users["A"]))
            if kind == "expired":
                ctx.api.clock.now = session.access_expires_at + timedelta(seconds=1)
            if kind == "revoked":
                session.revoked_at = ctx.api.clock.now
                session.revocation_reason = "LOGOUT"
            if kind == "inactive":
                db.get(User, ctx.users["A"]).status = "DEACTIVATED"
    response = ctx.api.client.get("/api/v1/summary", headers=headers)
    assert response.status_code == (403 if kind == "inactive" else 401), response.text
    assert response.json()["error"]["code"] == expected
    assert response.headers["Cache-Control"] == "no-store"
    if response.status_code == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_openapi():
    spec = create_app().openapi()
    assert {path for path in spec["paths"] if "/summary" in path} == {"/api/v1/summary"}
    path = spec["paths"]["/api/v1/summary"]
    assert set(path) == {"get"}
    op = path["get"]
    assert op["security"] == [{"HTTPBearer": []}]
    assert not op.get("parameters") and "requestBody" not in op
    assert set(op["responses"]) == {"200", "400", "401", "403", "422", "500", "503"}
    for response in op["responses"].values():
        assert {"Cache-Control", "X-Request-ID"} <= set(response["headers"])
    schemas = spec["components"]["schemas"]
    root = schemas["SummaryResponse"]
    assert root["additionalProperties"] is False
    assert root["required"] == ["currencies"] and set(root["properties"]) == {"currencies"}
    items = root["properties"]["currencies"]
    assert items["minItems"] == items["maxItems"] == 3
    for ref, currency in zip(items["prefixItems"], ("INR", "USD", "GBP"), strict=True):
        row = schemas[ref["$ref"].split("/")[-1]]
        assert row["additionalProperties"] is False
        assert set(row["properties"]) == set(row["required"]) == set(ZERO["currencies"][0])
        assert row["properties"]["currency"]["const"] == currency
        for field in (
            "borrowed_outstanding_minor",
            "lent_outstanding_minor",
            "net_position_minor",
        ):
            value = row["properties"][field]
            assert value["type"] == "integer" and value["maximum"] == MAX_SAFE_INTEGER
            assert value["minimum"] == (-MAX_SAFE_INTEGER if field == "net_position_minor" else 0)


@pytest.mark.parametrize(
    "kind",
    [
        "root_extra",
        "row_extra",
        "null",
        "missing",
        "float",
        "bool",
        "string",
        "negative",
        "order",
        "duplicate",
        "short",
        "long",
        "bad_net",
        "overflow",
    ],
)
def test_closed_schema(kind):
    value = deepcopy(ZERO)
    row = value["currencies"][0]
    if kind == "root_extra":
        value["user_id"] = "x"
    if kind == "row_extra":
        row["phone"] = "private"
    if kind == "null":
        row["net_position_minor"] = None
    if kind == "missing":
        row.pop("currency")
    if kind == "float":
        row["borrowed_outstanding_minor"] = 1.0
    if kind == "bool":
        row["borrowed_outstanding_minor"] = True
    if kind == "string":
        row["borrowed_outstanding_minor"] = "0"
    if kind == "negative":
        row["borrowed_outstanding_minor"] = -1
    if kind == "order":
        value["currencies"].reverse()
    if kind == "duplicate":
        value["currencies"][1] = row
    if kind == "short":
        value["currencies"].pop()
    if kind == "long":
        value["currencies"].append(row)
    if kind == "bad_net":
        row["net_position_minor"] = 1
    if kind == "overflow":
        row["lent_outstanding_minor"] = row["net_position_minor"] = MAX_SAFE_INTEGER + 1
    with pytest.raises(ValidationError):
        SummaryResponse.model_validate(value)


@pytest.mark.parametrize("side", ["borrowed", "lent"])
def test_safe_integer_boundary(side):
    value = deepcopy(ZERO)
    value["currencies"][0][side + "_outstanding_minor"] = MAX_SAFE_INTEGER
    value["currencies"][0]["net_position_minor"] = MAX_SAFE_INTEGER * (
        -1 if side == "borrowed" else 1
    )
    assert SummaryResponse.model_validate(value).model_dump(mode="json") == value


def test_no_idempotency_or_private_fields(b7):
    result = read(b7)
    assert result.status_code == 200
    for row in result.json()["currencies"]:
        assert set(row) == set(ZERO["currencies"][0])
        assert all(type(v) is int for k, v in row.items() if k != "currency")
    for private in (*b7.phones.values(), str(b7.users["A"]), b7.identifier):
        assert private not in result.text


@pytest.mark.parametrize("path", ["borrowed", "lent", "upcoming", "overdue", "activity"])
def test_deferred_routes(ctx, path):
    assert (
        ctx.api.client.get("/api/v1/summary/" + path, headers=ctx.headers["A"]).status_code == 404
    )


@pytest.mark.parametrize("error,status", [(RuntimeError, 500), (SQLAlchemyError, 503)])
def test_safe_failure_headers(ctx, monkeypatch, error, status):
    if error is SQLAlchemyError:
        monkeypatch.setattr(
            ctx.api.challenges.session_service,
            "revalidate_user_locked",
            lambda *args: (_ for _ in ()).throw(error("secret")),
        )
    else:

        class Broken:
            def read(self, *args):
                raise error("secret")

        ctx.api.app.dependency_overrides[get_summary_service] = lambda: Broken()
    result = ctx.api.client.get(
        "/api/v1/summary", headers={**ctx.headers["A"], "X-Request-ID": "bad secret id"}
    )
    assert result.status_code == status, result.text
    assert "secret" not in result.text
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Request-ID"] != "bad secret id"
