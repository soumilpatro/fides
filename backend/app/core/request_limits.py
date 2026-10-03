"""B14 bounded body admission before any downstream application execution."""

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import request_too_large_response

MAX_REQUEST_BODY_BYTES = 1_048_576


def _declared_oversize(value: bytes) -> bool:
    # Avoid unbounded integer conversion for hostile/invalid header values.
    value = value.strip(b" \t")
    if not value or not value.isdigit():
        return False
    significant = value.lstrip(b"0") or b"0"
    limit = str(MAX_REQUEST_BODY_BYTES).encode("ascii")
    return len(significant) > len(limit) or (len(significant) == len(limit) and significant > limit)


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if any(
            name.lower() == b"content-length" and _declared_oversize(value)
            for name, value in scope["headers"]
        ):
            await request_too_large_response(Request(scope))(scope, receive, send)
            return

        # A receive-only wrapper would let body-ignoring handlers or auth
        # dependencies execute before oversize is discovered. Admit the entire
        # body first, retaining at most the ceiling and never an over-limit chunk.
        buffer = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(buffer) + len(chunk) > MAX_REQUEST_BODY_BYTES:
                await request_too_large_response(Request(scope))(scope, receive, send)
                return
            buffer.extend(chunk)
            if not message.get("more_body", False):
                break

        body = bytes(buffer)
        buffer.clear()
        delivered = False

        async def replay() -> dict:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
