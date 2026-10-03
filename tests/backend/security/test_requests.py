import asyncio
import json

import pytest

LIMIT = 1_048_576
OTP = "/api/v1/auth/otp/request"
JSON = b'{"intent":"signup","phone":"+14155552671"}'


def payload(size):
    return JSON + b" " * (size - len(JSON))


def assert_rejected(response):
    assert response.status_code == 413
    assert response.json() == {
        "error": {"code": "REQUEST_TOO_LARGE", "message": "Request too large."}
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("size", [len(JSON), LIMIT, LIMIT + 1])
def test_actual_otp_body_boundary(security_client, security_app, size):
    response = security_client.post(
        OTP, content=payload(size), headers={"Content-Type": "application/json"}
    )
    if size > LIMIT:
        assert_rejected(response)
        assert not security_app.calls
    else:
        assert response.status_code == 202
        assert len(security_app.calls) == 1
        assert security_app.calls[0].intent == "signup"


@pytest.mark.parametrize("declared", [None, b"8", b"1048576"])
def test_streamed_actual_bytes_and_stop_reading(security_app, declared):
    async def scenario():
        reads = 0
        messages = iter(
            [
                {"type": "http.request", "body": payload(LIMIT), "more_body": True},
                {"type": "http.request", "body": b" ", "more_body": True},
                {"type": "http.request", "body": b"unread", "more_body": False},
            ]
        )
        sent = []

        async def receive():
            nonlocal reads
            reads += 1
            return next(messages)

        async def send(message):
            sent.append(message)

        headers = [(b"content-type", b"application/json"), (b"x-request-id", b"bounded-id")]
        if declared is not None:
            headers.append((b"content-length", declared))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": OTP,
            "raw_path": OTP.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("192.0.2.1", 1000),
            "server": ("audit.invalid", 80),
        }
        await security_app.app(scope, receive, send)
        assert reads == 2
        assert sent[0]["status"] == 413
        assert dict(sent[0]["headers"])[b"x-request-id"] == b"bounded-id"
        assert json.loads(b"".join(m.get("body", b"") for m in sent)) == {
            "error": {"code": "REQUEST_TOO_LARGE", "message": "Request too large."}
        }
        assert not security_app.calls

    asyncio.run(scenario())


@pytest.mark.parametrize("request_id", ["safe-id", "unsafe id !", "x" * 65])
def test_declared_oversize_correlation_and_no_service(security_client, security_app, request_id):
    response = security_client.post(
        OTP,
        content=JSON,
        headers={"Content-Length": str(LIMIT + 1), "X-Request-ID": request_id},
    )
    assert_rejected(response)
    reflected = response.headers["x-request-id"]
    assert (reflected == request_id) if request_id == "safe-id" else (reflected != request_id)
    assert len(reflected) <= 64
    assert not security_app.calls


def test_openapi_documents_approved_413(security_app):
    for path, methods in security_app.app.openapi()["paths"].items():
        if path.startswith("/api/v1/"):
            for operation in methods.values():
                assert "413" in operation["responses"]
                assert operation["responses"]["413"]["description"] == "REQUEST_TOO_LARGE"
