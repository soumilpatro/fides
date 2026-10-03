from uuid import uuid4

import pytest
from app.api.closure_requests import get_closure_service
from app.main import create_app

from .conftest import error, requested

COLLECTION = "/api/v1/commitments/{id}/closure-requests"
CHILD = "/api/v1/closure-requests/{id}"
FIELDS = {
    "id",
    "commitment_id",
    "requested_by",
    "counterparty",
    "status",
    "currency",
    "outstanding_snapshot_minor",
    "waived_amount_minor",
    "note",
    "decided_by",
    "decided_at",
    "created_at",
    "updated_at",
}
ROUTES = [
    ("post", COLLECTION),
    ("get", COLLECTION),
    ("get", CHILD),
    *[("post", CHILD + "/" + a) for a in ("accept", "reject", "cancel")],
]


def test_exact_openapi_contract():
    schema = create_app().openapi()
    assert {
        (method, path)
        for path, ops in schema["paths"].items()
        if "closure-requests" in path
        for method in ops
    } == set(ROUTES)
    models = schema["components"]["schemas"]
    assert set(models["ClosureResponse"]["properties"]) == FIELDS
    assert set(models["ClosureResponse"]["required"]) == FIELDS
    assert models["ClosureResponse"]["additionalProperties"] is False
    assert set(models["ClosureRequestCreate"]["properties"]) == {"note"}
    assert models["ClosureRequestCreate"]["additionalProperties"] is False
    assert models["MutualClosureStatus"]["enum"] == [
        "REQUESTED",
        "ACCEPTED",
        "REJECTED",
        "CANCELLED",
    ]
    for method, path in ROUTES:
        op = schema["paths"][path][method]
        assert op["security"] == [{"HTTPBearer": []}]
        assert {p["name"] for p in op["parameters"]} == (
            {"id", "Idempotency-Key"} if method == "post" else {"id"}
        )
        status = "201" if method == "post" and path == COLLECTION else "200"
        assert status in op["responses"]
        assert {"400", "401", "403", "404", "409", "413", "422", "500", "503"} <= set(
            op["responses"]
        )
        assert op["responses"][status]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
        if method == "post":
            assert op["requestBody"]["required"]


@pytest.mark.parametrize("method,path", ROUTES)
def test_missing_auth(mc, method, path):
    response = mc.api.client.request(
        method, path.replace("{id}", str(uuid4())), json={} if method == "post" else None
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path", [p for m, p in ROUTES if m == "post"])
@pytest.mark.parametrize("key", [None, "", "bad key"])
def test_required_key(mc, path, key):
    headers = dict(mc.headers["A"])
    if key is not None:
        headers["Idempotency-Key"] = key
    response = mc.api.client.post(path.replace("{id}", mc.identifier), json={}, headers=headers)
    error(response, "MALFORMED_REQUEST", 400)


@pytest.mark.parametrize("path", [p for m, p in ROUTES if m == "post"])
@pytest.mark.parametrize(
    "body,code,status",
    [
        ("{", "MALFORMED_REQUEST", 400),
        ("", "VALIDATION_ERROR", 422),
        ("null", "VALIDATION_ERROR", 422),
        ("[]", "VALIDATION_ERROR", 422),
        ('{"amount_minor":1}', "VALIDATION_ERROR", 422),
        ('{"principal_amount_minor":1}', "VALIDATION_ERROR", 422),
    ],
)
def test_body_errors_and_headers(mc, path, body, code, status):
    response = mc.api.client.post(
        path.replace("{id}", mc.identifier),
        content=body,
        headers={
            **mc.headers["A"],
            "Idempotency-Key": uuid4().hex,
            "Content-Type": "application/json",
            "X-Request-ID": "closure-contract",
            "Host": "malformed:host:bad",
        },
    )
    error(response, code, status)
    assert response.headers["X-Request-ID"] == "closure-contract"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert set(response.json()) == {"error"}


@pytest.mark.parametrize("path", [p for m, p in ROUTES if m == "post"])
@pytest.mark.parametrize("declared", ["1", "1048577"])
def test_oversized_never_invokes_service(mc, path, declared):
    def must_not_run():
        raise AssertionError("Oversized body reached dependency")

    app = mc.api.client.app
    app.dependency_overrides[get_closure_service] = must_not_run
    try:
        response = mc.api.client.post(
            path.replace("{id}", mc.identifier),
            content=b"x" * 1048577,
            headers={**mc.headers["A"], "Content-Length": declared, "X-Request-ID": "closure-size"},
        )
    finally:
        app.dependency_overrides.pop(get_closure_service)
    error(response, "REQUEST_TOO_LARGE", 413)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"] == "closure-size"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("action", ["accept", "reject", "cancel"])
def test_exact_response_and_success_headers(mc, action):
    identifier = requested(mc)
    response = mc.decide(identifier, action, actor="A" if action == "cancel" else "B")
    assert response.status_code == 200
    for result in (response, mc.closure_read(identifier=identifier)):
        body = result.json()
        assert set(body) == FIELDS
        assert all(
            set(body[name]) == {"id", "display_name"}
            for name in ("requested_by", "counterparty", "decided_by")
        )
        assert not any(word in result.text for word in ("phone", "token", "session", "identity"))
        assert result.headers["Cache-Control"] == "no-store"
        assert result.headers["X-Request-ID"]
        assert result.headers["X-Content-Type-Options"] == "nosniff"
        assert result.headers["Referrer-Policy"] == "no-referrer"


def test_exact_body_ceiling_remains_readable(mc):
    response = mc.api.client.post(
        COLLECTION.replace("{id}", mc.identifier),
        content=b"{}" + b" " * (1048576 - 2),
        headers={
            **mc.headers["A"],
            "Idempotency-Key": uuid4().hex,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 201, response.text


def test_streamed_oversize_and_sanitized_correlation(mc):
    def chunks():
        yield b"{" + b" " * 524288
        yield b" " * 524288
        yield b"}"

    response = mc.api.client.post(
        COLLECTION.replace("{id}", mc.identifier),
        content=chunks(),
        headers={**mc.headers["A"], "Idempotency-Key": uuid4().hex, "X-Request-ID": "private<>id"},
    )
    error(response, "REQUEST_TOO_LARGE", 413)
    assert response.headers["X-Request-ID"] != "private<>id"
    assert response.headers["Cache-Control"] == "no-store"


def test_safe_unhandled_failure(mc, caplog):
    class FailedService:
        def create(self, *args, **kwargs):
            raise RuntimeError("private note phone SQL token")

    app = mc.api.client.app
    app.dependency_overrides[get_closure_service] = FailedService
    try:
        response = mc.create()
    finally:
        app.dependency_overrides.pop(get_closure_service)
    error(response, "INTERNAL_ERROR", 500)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "private note phone SQL token" not in response.text + caplog.text
