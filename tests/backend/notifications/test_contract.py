from uuid import uuid4

import pytest
from app.main import create_app

from .conftest import TYPES, make

BASE = "/api/v1/notifications"
FIELDS = {
    "id",
    "type",
    "actor",
    "commitment_id",
    "repayment_id",
    "extension_request_id",
    "created_at",
    "read_at",
}


def test_openapi():
    spec = create_app().openapi()
    assert {
        p: set(v) for p, v in spec["paths"].items() if p == BASE or p.startswith(BASE + "/")
    } == {
        BASE: {"get"},
        BASE + "/{id}/read": {"post"},
    }
    schemas = spec["components"]["schemas"]
    row = schemas["NotificationResponse"]
    assert set(row["properties"]) == set(row["required"]) == FIELDS
    assert row["additionalProperties"] is False
    assert set(row["properties"]["type"]["enum"]) == set(TYPES) | {
        "UPCOMING_DUE",
        "DUE_TODAY",
        "OVERDUE",
    }
    assert any(part.get("type") == "null" for part in row["properties"]["actor"]["anyOf"])
    assert set(schemas["NotificationListResponse"]["properties"]) == {"items", "next_cursor"}
    for path, method in [(BASE, "get"), (BASE + "/{id}/read", "post")]:
        op = spec["paths"][path][method]
        assert op["security"] == [{"HTTPBearer": []}]
        assert {p["name"] for p in op["parameters"]} == (
            {"limit", "cursor"} if method == "get" else {"id"}
        )
        for code in (200, 400, 401, 403, 404, 422, 500, 503):
            assert str(code) in op["responses"]
            assert "Cache-Control" in op["responses"][str(code)]["headers"]
        assert "409" not in op["responses"]
    op = spec["paths"][BASE + "/{id}/read"]["post"]
    assert op["requestBody"]["required"]
    body = schemas[
        op["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    ]
    assert body["properties"] == {} and body["additionalProperties"] is False
    limit = next(p for p in spec["paths"][BASE]["get"]["parameters"] if p["name"] == "limit")[
        "schema"
    ]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 100, 50)


@pytest.mark.parametrize(
    "raw,code",
    [("{}", 200), ("", 422), ("null", 422), ("[]", 422), ("true", 422), ('"x"', 422), ("{", 400)],
)
def test_closed_body(inbox, raw, code):
    result = inbox.api.client.post(
        f"{BASE}/{make(inbox)}/read",
        content=raw,
        headers={**inbox.headers["B"], "Content-Type": "application/json"},
    )
    assert result.status_code == code, result.text
    if code == 400:
        assert result.json()["error"]["code"] == "MALFORMED_REQUEST"


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "user_id",
        "recipient",
        "status",
        "read_at",
        "id",
        "payload",
        "source_ledger_event_id",
    ],
)
def test_overposting(inbox, field):
    result = inbox.mark(make(inbox), json={field: "injected"})
    assert result.status_code == 422 and result.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("token", [None, "invalid"])
def test_auth_headers(inbox, method, token):
    path = BASE if method == "get" else f"{BASE}/{make(inbox)}/read"
    result = inbox.api.client.request(
        method, path, json={}, headers={} if token is None else {"Authorization": "Bearer " + token}
    )
    assert result.status_code == 401
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["WWW-Authenticate"] == "Bearer"
    assert result.headers["X-Request-ID"]


@pytest.mark.parametrize("request_id", ["safe-request.1", "unsafe !", "x" * 65])
def test_exact_response_headers_no_key(inbox, request_id):
    identifier = make(inbox)
    response = inbox.api.client.post(
        f"{BASE}/{identifier}/read",
        json={},
        headers={**inbox.headers["B"], "X-Request-ID": request_id},
    )
    assert response.status_code == 200
    assert set(response.json()) == FIELDS
    assert set(response.json()["actor"]) == {"id", "display_name"}
    assert response.json()["created_at"].endswith("Z") and response.json()["read_at"].endswith("Z")
    assert response.headers["Cache-Control"] == "no-store"
    assert (response.headers["X-Request-ID"] == request_id) == (request_id == "safe-request.1")


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", BASE + "/" + str(uuid4())),
        ("POST", BASE + "/read"),
        ("POST", BASE + "/read-all"),
        ("POST", BASE + "/" + str(uuid4()) + "/unread"),
        ("PATCH", BASE + "/" + str(uuid4())),
        ("DELETE", BASE + "/" + str(uuid4())),
        ("PATCH", "/api/v1/notification-preferences"),
        ("DELETE", "/api/v1/notification-preferences"),
        ("POST", "/api/v1/push-tokens"),
        ("GET", "/api/v1/reminders"),
        ("GET", "/api/v1/admin/notifications"),
        ("GET", "/api/v1/audit"),
    ],
)
def test_absent_routes(inbox, method, path):
    assert inbox.api.client.request(
        method, path, headers=inbox.headers["A"], json={}
    ).status_code in (404, 405)


def test_invalid_uuid(inbox):
    assert inbox.mark("bad-id").status_code == 422
