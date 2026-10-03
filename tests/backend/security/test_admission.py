import asyncio

import pytest
from app.core.request_limits import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware
from starlette.responses import Response


@pytest.mark.parametrize(
    "chunks", [[b"a", b"b", b"c"], [b"", b"valid"], [b"x" * MAX_REQUEST_BODY_BYTES]]
)
def test_valid_stream_replayed_to_downstream(chunks):
    async def scenario():
        messages = iter(
            [
                {"type": "http.request", "body": body, "more_body": index < len(chunks) - 1}
                for index, body in enumerate(chunks)
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        async def downstream(scope, replay, send):
            message = await replay()
            assert message["body"] == b"".join(chunks)
            assert message["more_body"] is False
            await Response(status_code=200)(scope, replay, send)

        await RequestBodyLimitMiddleware(downstream)({"type": "http", "headers": []}, receive, send)
        assert sent[0]["status"] == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("length", [b"1048577", b"0001048577", b"9" * 5000, b" \t1048577 \t"])
def test_declared_oversize_never_reads_or_dispatches(security_app, length):
    async def scenario():
        sent = []

        async def receive():
            raise AssertionError("Oversized declared body must not be read")

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/auth/otp/request",
            "raw_path": b"/api/v1/auth/otp/request",
            "query_string": b"",
            "headers": [(b"content-length", length)],
            "client": ("192.0.2.1", 1000),
            "server": ("audit.invalid", 80),
        }
        await security_app.app(scope, receive, send)
        assert sent[0]["status"] == 413
        assert not security_app.calls

    asyncio.run(scenario())


def test_body_ignoring_endpoint_cannot_run_on_actual_oversize(security_client):
    response = security_client.request(
        "GET",
        "/api/v1/auth/security-test/failure",
        # Declared size is deliberately misleading; actual bytes govern.
        content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
        headers={"Content-Length": "1"},
    )
    assert response.status_code == 413
