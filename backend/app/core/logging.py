"""Structured logging and request-correlation foundations (B0 scope).

This module provides:
- JSON-structured log output (no secrets, no unnecessary PII).
- A request-correlation ID generated per request (or propagated from an
  inbound `X-Request-ID` header) so log lines for a single request can be
  tied together, per AI Build Spec B0 item: "Add consistent error handling
  and request correlation/logging foundations."

No financial or authentication data exists yet at B0, so redaction rules
for domain-specific sensitive fields are deferred to the phases that
introduce those fields (B2 auth, B5+ financial domain). This module must
not be assumed to fully satisfy later logging/privacy requirements
(Tech Spec Sec. 22-23) — those are re-validated in B14 (Security hardening).
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_REQUEST_ID_HEADER = "X-Request-ID"
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def sanitize_request_id(value: str | None) -> str:
    """Accept bounded ASCII correlation IDs; never reflect arbitrary header text."""
    if value and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value):
        return value
    return str(uuid.uuid4())


class _JsonFormatter(logging.Formatter):
    """Minimal structured (JSON) log formatter.

    Emits standard fields plus the current request correlation ID.
    Deliberately does not include arbitrary extra kwargs by default to
    avoid accidentally logging sensitive data; callers must pass explicit,
    reviewed fields via `extra={"fields": {...}}` if needed later.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _request_id_ctx.get(),
        }
        extra_fields = getattr(record, "fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure root logging with the structured JSON formatter.

    Safe to call multiple times (e.g. in tests); resets existing handlers
    on the root logger to avoid duplicate log lines.
    """
    root = logging.getLogger()
    root.setLevel(log_level.upper())

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Assign/propagate a request correlation ID for each HTTP request.

    - If the inbound request carries `X-Request-ID`, it is reused.
    - Otherwise a new UUID4 is generated.
    - The ID is stored in a ContextVar so log lines emitted anywhere during
      request handling can include it, and is echoed back on the response.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming_id = request.headers.get(_REQUEST_ID_HEADER)
        request_id = sanitize_request_id(incoming_id)
        request.state.request_id = request_id
        token = _request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            _request_id_ctx.reset(token)
        response.headers[_REQUEST_ID_HEADER] = request_id
        if request.url.path.startswith(
            (
                "/api/v1/auth/",
                "/api/v1/me",
                "/api/v1/connections",
                "/api/v1/commitments",
                "/api/v1/repayments",
            )
        ):
            response.headers["Cache-Control"] = "no-store"
        return response


def get_request_id() -> str:
    """Return the correlation ID for the request currently being handled."""
    return _request_id_ctx.get()
