"""Stable errors exercise existing handlers using test-only routes."""

import logging
import re
from pathlib import Path

import pytest
from app.api.auth_schemas import OtpRequest
from app.core.errors import AUTH_ERRORS, AuthError, register_exception_handlers
from app.core.logging import RequestCorrelationMiddleware
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def approved_errors():
    decisions = (Path(__file__).resolve().parents[2] / "DECISIONS.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d{3}) \| ([A-Z_]+) \| ([^|]+) \|$", decisions, re.MULTILINE)
    return {code: (int(status), message) for status, code, message in rows}


@pytest.mark.parametrize("code, expected", approved_errors().items())
def test_approved_error_envelope_status_and_headers(code, expected):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/test-error")
    def error():
        raise AuthError(
            code,
            retry_after_seconds=60,
            headers={
                "X-Request-ID": "reviewed-id",
                "X-Test": "preserved",
            },
        )

    with TestClient(app) as client:
        response = client.get("/test-error")
    status, message = expected
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": message}}
    assert response.headers["X-Request-ID"] == "reviewed-id"
    assert response.headers["X-Test"] == "preserved"
    assert response.headers["Cache-Control"] == "no-store"
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"
    if status == 429:
        assert response.headers["Retry-After"] == "60"


def test_catalog_closed_and_removed_error_absent():
    assert len(approved_errors()) == 25
    assert dict(AUTH_ERRORS) == approved_errors()
    assert "AUTH_CHALLENGE_CONFLICT" not in AUTH_ERRORS
    with pytest.raises(KeyError):
        AuthError("UNAPPROVED_CODE")
    with pytest.raises(ValueError):
        AuthError("OTP_RATE_LIMITED")


@pytest.mark.parametrize(
    "body, expected",
    [
        ('{"secret":', (400, "MALFORMED_REQUEST")),
        ('{"intent":"signup","phone":123}', (422, "VALIDATION_ERROR")),
        ('{"intent":"signup","phone":"not-a-phone"}', (422, "INVALID_PHONE")),
        (
            '{"intent":"signup","phone":"+919876543210","display_name":"private"}',
            (422, "VALIDATION_ERROR"),
        ),
    ],
)
def test_validation_error_mapping_and_safe_request_ids(body, expected):
    app = FastAPI()
    app.add_middleware(RequestCorrelationMiddleware)
    register_exception_handlers(app)

    @app.post("/api/v1/auth/test-only")
    def validate(request: OtpRequest):
        return {}

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/test-only",
            content=body,
            headers={"Content-Type": "application/json", "X-Request-ID": "x" * 65},
        )
    assert (response.status_code, response.json()["error"]["code"]) == expected
    assert re.fullmatch(r"[a-f0-9-]{36}", response.headers["X-Request-ID"])
    assert response.headers["Cache-Control"] == "no-store"
    assert "private" not in response.text


def test_http_exception_headers_are_preserved():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/test")
    def fail():
        raise HTTPException(
            401,
            "Denied",
            headers={"WWW-Authenticate": "Bearer", "Retry-After": "5", "Cache-Control": "no-store"},
        )

    with TestClient(app) as client:
        response = client.get("/test")
    assert response.json()["error"]["code"] == "HTTP_ERROR"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Retry-After"] == "5"
    assert response.headers["Cache-Control"] == "no-store"


def test_unhandled_errors_do_not_log_exception_secrets(caplog):
    app = FastAPI()
    app.add_middleware(RequestCorrelationMiddleware)
    register_exception_handlers(app)

    @app.get("/api/v1/auth/test-only")
    def fail():
        raise RuntimeError("private-otp-token-sql-bind")

    with caplog.at_level(logging.ERROR), TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/auth/test-only", headers={"X-Request-ID": "safe-id"})
    assert response.status_code == 500
    assert "private-otp-token-sql-bind" not in response.text + caplog.text
    assert response.headers["X-Request-ID"] == "safe-id"
    assert response.headers["Cache-Control"] == "no-store"


def test_security_headers_are_case_insensitive():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/test-error")
    def error():
        raise AuthError(
            "AUTH_REQUIRED",
            headers={
                "cache-control": "public",
                "www-authenticate": "obsolete",
                "x-request-id": "safe-id",
            },
        )

    with TestClient(app) as client:
        response = client.get("/test-error")
    assert response.headers.get_list("cache-control") == ["no-store"]
    assert response.headers.get_list("www-authenticate") == ["Bearer"]
    assert response.headers.get_list("x-request-id") == ["safe-id"]


def test_b0_validation_behavior_is_preserved():
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/test-b0")
    def validate(request: OtpRequest):
        return {}

    with TestClient(app) as client:
        response = client.post(
            "/test-b0", content="{", headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "VALIDATION_ERROR", "message": "Request validation failed."}
    }


@pytest.mark.parametrize("path", ["/test-b0", "/api/v1/auth/test-only"])
@pytest.mark.parametrize(
    "status, expected_message",
    [
        (400, "Bad Request"),
        (401, "Unauthorized"),
        (404, "Not Found"),
        (500, "Internal Server Error"),
        (599, "Request failed."),
    ],
)
@pytest.mark.parametrize(
    "detail", ["test-only-private-token", {"secret": "test-only-private-token"}]
)
def test_http_exception_detail_is_never_public_or_logged(
    path, status, expected_message, detail, caplog
):
    app = FastAPI()
    app.add_middleware(RequestCorrelationMiddleware)
    register_exception_handlers(app)

    @app.get(path)
    def error():
        raise HTTPException(
            status, detail, headers={"WWW-Authenticate": "Bearer", "Retry-After": "5"}
        )

    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        response = client.get(path, headers={"X-Request-ID": "safe-id"})
    assert response.status_code == status
    assert response.json() == {"error": {"code": "HTTP_ERROR", "message": expected_message}}
    assert "test-only-private-token" not in response.text + caplog.text
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Retry-After"] == "5"
    assert response.headers["X-Request-ID"] == "safe-id"
    if path.startswith("/api/v1/auth/"):
        assert response.headers["Cache-Control"] == "no-store"
