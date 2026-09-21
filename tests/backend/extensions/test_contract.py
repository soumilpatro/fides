from uuid import uuid4

import pytest
from app.main import create_app

from .conftest import requested

COLLECTION = "/api/v1/commitments/{id}/extension-requests"
DECISION = "/api/v1/extension-requests/{id}"
FIELDS = {
    "id",
    "commitment_id",
    "requested_by",
    "status",
    "base_terms_version_id",
    "previous_due_date",
    "requested_due_date",
    "reason",
    "decided_by",
    "decided_at",
    "created_at",
}


def test_openapi():
    schema = create_app().openapi()
    paths = {p: set(ops) for p, ops in schema["paths"].items() if "extension" in p}
    assert paths == {
        COLLECTION: {"post", "get"},
        DECISION + "/accept": {"post"},
        DECISION + "/reject": {"post"},
    }
    models = schema["components"]["schemas"]
    assert set(models["ExtensionResponse"]["properties"]) == FIELDS
    assert models["ExtensionResponse"]["additionalProperties"] is False
    assert set(models["ExtensionResponse"]["required"]) == FIELDS
    assert set(models["ExtensionRequestBody"]["properties"]) == {"requested_due_date", "reason"}
    assert models["ExtensionRequestBody"]["required"] == ["requested_due_date"]
    assert models["ExtensionRequestBody"]["additionalProperties"] is False
    for path, methods in paths.items():
        for method in methods:
            op = schema["paths"][path][method]
            assert op["security"] == [{"HTTPBearer": []}]
            assert {p["name"] for p in op["parameters"]} == (
                {"id", "Idempotency-Key"} if method == "post" else {"id"}
            )
            status = "201" if path == COLLECTION and method == "post" else "200"
            assert status in op["responses"]
            for code in (400, 401, 403, 404, 409, 422, 500, 503):
                assert str(code) in op["responses"]
            if method == "post":
                assert op["requestBody"]["required"]
    assert not any("audit" in p for p in schema["paths"])


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"requested_due_date": None},
        {"requested_due_date": 123},
        {"requested_due_date": True},
        {"requested_due_date": "2026-02-30"},
        {"requested_due_date": "2026-1-01"},
        {"requested_due_date": "2026-12-01T00:00:00Z"},
        {"requested_due_date": []},
        {"requested_due_date": " 2026-12-01"},
    ],
)
def test_invalid_create_dates(b10, body):
    result = b10.api.client.post(
        COLLECTION.replace("{id}", b10.identifier),
        json=body,
        headers={**b10.headers["A"], "Idempotency-Key": uuid4().hex},
    )
    assert result.status_code == 422 and result.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "value,valid,expected",
    [
        (None, True, None),
        ("", True, None),
        ("  ", True, None),
        (" hi ", True, "hi"),
        ("x" * 500, True, "x" * 500),
        (" " + "x" * 500 + " ", True, "x" * 500),
        ("x" * 501, False, None),
        (1, False, None),
        (False, False, None),
        ([], False, None),
        ({}, False, None),
    ],
)
def test_reason(b10, value, valid, expected):
    result = b10.create(reason=value)
    assert result.status_code == (201 if valid else 422)
    if valid:
        assert result.json()["reason"] == expected


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "requester_id",
        "status",
        "base_terms_version_id",
        "previous_due_date",
        "created_at",
        "interest_type",
        "interest_rate_bps",
        "grace_period_days",
        "installment_dates",
        "principal_amount_minor",
        "currency",
        "requested_terms",
    ],
)
def test_overposting(b10, field):
    response = b10.api.client.post(
        COLLECTION.replace("{id}", b10.identifier),
        json={"requested_due_date": "2026-11-10", field: "injected"},
        headers={**b10.headers["A"], "Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("action", ["accept", "reject"])
@pytest.mark.parametrize(
    "raw,code",
    [
        ("{}", 200),
        ("null", 422),
        ("[]", 422),
        ('{"decision_note":"private"}', 422),
        ('{"actor":"bad"}', 422),
        ("{", 400),
        ("", 422),
    ],
)
def test_decision_body(b10, action, raw, code):
    identifier = requested(b10)
    response = b10.api.client.post(
        DECISION.replace("{id}", identifier) + "/" + action,
        content=raw,
        headers={
            **b10.headers["B"],
            "Idempotency-Key": uuid4().hex,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == code, response.text
    if code == 400:
        assert response.json()["error"]["code"] == "MALFORMED_REQUEST"


@pytest.mark.parametrize("operation", ["create", "accept", "reject"])
@pytest.mark.parametrize("key", [None, "", "bad key", "x" * 129])
def test_keys(b10, operation, key):
    path = (
        COLLECTION.replace("{id}", b10.identifier)
        if operation == "create"
        else (DECISION.replace("{id}", requested(b10)) + "/" + operation)
    )
    headers = dict(b10.headers["A" if operation == "create" else "B"])
    if key is not None:
        headers["Idempotency-Key"] = key
    result = b10.api.client.post(
        path,
        headers=headers,
        json={"requested_due_date": "2026-11-10"} if operation == "create" else {},
    )
    assert result.status_code == 400 and result.json()["error"]["code"] == "MALFORMED_REQUEST"


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_response_and_headers(b10, action):
    creation = b10.create(reason="private reason")
    assert creation.status_code == 201
    row = creation.json()
    assert set(row) == FIELDS
    assert row["status"] == "REQUESTED" and row["decided_by"] is row["decided_at"] is None
    result = b10.api.client.post(
        DECISION.replace("{id}", row["id"]) + "/" + action,
        json={},
        headers={**b10.headers["B"], "Idempotency-Key": uuid4().hex, "X-Request-ID": "unsafe !"},
    )
    assert result.status_code == 200
    assert set(result.json()) == FIELDS
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Request-ID"] != "unsafe !"
    assert result.json()["created_at"].endswith("Z")
    assert result.json()["decided_at"].endswith("Z")
    assert b10.read().json() == [result.json()]
    for phone in b10.phones.values():
        assert phone not in result.text


@pytest.mark.parametrize(
    "suffix,method",
    [
        ("", "GET"),
        ("/approve", "POST"),
        ("/cancel", "POST"),
        ("/decision", "POST"),
        ("/accept", "DELETE"),
    ],
)
def test_absent_routes(b10, suffix, method):
    result = b10.api.client.request(
        method, DECISION.replace("{id}", str(uuid4())) + suffix, headers=b10.headers["A"]
    )
    assert result.status_code in (404, 405)


@pytest.mark.parametrize("operation", ["create", "read", "accept", "reject"])
@pytest.mark.parametrize("token", [None, "invalid"])
def test_auth_required(b10, operation, token):
    path = (
        COLLECTION.replace("{id}", b10.identifier)
        if operation in ("create", "read")
        else DECISION.replace("{id}", requested(b10)) + "/" + operation
    )
    headers = {"Idempotency-Key": uuid4().hex}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    result = b10.api.client.request(
        "GET" if operation == "read" else "POST",
        path,
        json={"requested_due_date": "2026-11-10"} if operation == "create" else {},
        headers=headers,
    )
    assert result.status_code == 401
    assert result.headers["WWW-Authenticate"] == "Bearer"
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Request-ID"]


def test_malformed_create_json(b10):
    result = b10.api.client.post(
        COLLECTION.replace("{id}", b10.identifier),
        content="{",
        headers={
            **b10.headers["A"],
            "Idempotency-Key": uuid4().hex,
            "Content-Type": "application/json",
        },
    )
    assert result.status_code == 400 and result.json()["error"]["code"] == "MALFORMED_REQUEST"
