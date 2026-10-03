"""Consistent error-handling foundation for the FIDES backend (B0 scope).

Provides a uniform JSON error envelope and exception handlers so that:
- HTTPExceptions (e.g. 404 on an unknown route) return a stable shape.
- Unhandled exceptions never leak stack traces or internals to the client,
  per API Specification Sec. 10 ("Never expose stack traces or secrets")
  and Tech Specification Sec. 22/23.

B2 adds a closed catalog of approved auth errors without endpoint logic.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from http import HTTPStatus
from types import MappingProxyType

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import sanitize_request_id, set_api_response_headers

logger = logging.getLogger("fides.errors")

AUTH_ERRORS: Mapping[str, tuple[int, str]] = MappingProxyType(
    {
        "MALFORMED_REQUEST": (400, "Malformed request."),
        "AUTH_REQUIRED": (401, "Authentication is required."),
        "INVALID_AUTH_TOKEN": (401, "Invalid access token."),
        "AUTH_TOKEN_EXPIRED": (401, "Access token has expired."),
        "INVALID_REFRESH_TOKEN": (401, "Invalid refresh token."),
        "REFRESH_TOKEN_EXPIRED": (401, "Refresh token has expired."),
        "SESSION_REVOKED": (401, "Session has been revoked."),
        "INVALID_PHONE": (422, "Enter a valid international phone number."),
        "OTP_INVALID_CHALLENGE": (400, "Invalid verification challenge."),
        "OTP_INVALID": (400, "Invalid verification code."),
        "OTP_EXPIRED": (400, "Verification has expired. Request a new code."),
        "OTP_REPLAYED": (409, "Verification has already been used."),
        "OTP_CHALLENGE_UNAVAILABLE": (
            409,
            "Verification cannot be completed. Request a new code after its expiry.",
        ),
        "AUTH_CHALLENGE_BUSY": (409, "Verification is already being processed."),
        "OTP_RATE_LIMITED": (429, "Too many verification attempts. Try again later."),
        "AUTH_RATE_LIMITED": (429, "Too many authentication requests. Try again later."),
        "OTP_DELIVERY_UNAVAILABLE": (400, "SMS verification is unavailable for this number."),
        "AUTH_PROVIDER_UNAVAILABLE": (503, "Authentication is temporarily unavailable."),
        "AUTH_FLOW_NOT_ALLOWED": (409, "This authentication flow cannot be completed."),
        "ACCOUNT_DEACTIVATED": (403, "This account is deactivated."),
        "ACCOUNT_UNAVAILABLE": (403, "This account is unavailable."),
        "ACCOUNT_HAS_UNRESOLVED_COMMITMENTS": (
            409,
            "Resolve outstanding commitments before deactivating your account.",
        ),
        "VALIDATION_ERROR": (422, "Request validation failed."),
        "SERVICE_UNAVAILABLE": (503, "Service is temporarily unavailable."),
        "INTERNAL_ERROR": (500, "An unexpected error occurred."),
    }
)


class AuthError(Exception):
    """Fixed public code/message; headers are trusted server-generated metadata."""

    def __init__(
        self,
        code: str,
        *,
        headers: Mapping[str, str] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.status_code, self.message = AUTH_ERRORS[code]
        self.code = code
        self.headers = MutableHeaders(headers=headers)
        if self.status_code == 401:
            self.headers["WWW-Authenticate"] = "Bearer"
        if self.status_code == 429:
            if type(retry_after_seconds) is not int or retry_after_seconds < 0:
                raise ValueError("Rate-limit errors require non-negative integer Retry-After.")
            self.headers["Retry-After"] = str(retry_after_seconds)
        super().__init__(code)


class ConnectionError(Exception):
    """B4-D0 uses existing stable domain codes; no auth catalog changes."""

    def __init__(self, code: str):
        self.status_code, self.message = {
            "FORBIDDEN": (403, "Forbidden."),
            "INVALID_STATE": (409, "Invalid state."),
            "CONFLICT": (409, "Conflict."),
        }[code]
        self.code = code
        super().__init__(code)


class FinancialError(Exception):
    """B5 implements the approved financial vocabulary without changing B2/B4."""

    def __init__(self, code: str):
        self.status_code, self.message = {
            "FORBIDDEN": (403, "Forbidden."),
            "INVALID_STATE": (409, "Invalid state."),
            "CONFLICT": (409, "Conflict."),
            "IDEMPOTENCY_CONFLICT": (409, "Idempotency key conflicts with this request."),
            "INVALID_AMOUNT": (422, "Invalid amount."),
            "OVER_REPAYMENT": (409, "Repayment exceeds available reporting capacity."),
            "CURRENCY_MISMATCH": (422, "Currency does not match commitment."),
        }[code]
        self.code = code
        super().__init__(code)


class ResourceUnavailable(Exception):
    """Tech Spec v1.1 NOT_FOUND / API Spec v1.0 unavailable-resource contract."""

    code = "NOT_FOUND"
    message = "Unavailable resource."

    def __init__(self):
        super().__init__(self.code)


class VerificationError(FinancialError):
    """B8-specific vocabulary/wording; preserves B7 reporting messages."""

    def __init__(self, code: str):
        self.status_code, self.message = {
            "ALREADY_VERIFIED": (409, "Repayment is already verified."),
            "OVER_REPAYMENT": (409, "Repayment exceeds current verified outstanding."),
        }[code]
        self.code = code
        Exception.__init__(self, code)


def _is_auth_request(request: Request) -> bool:
    return request.scope["path"].startswith(("/api/v1/auth/", "/api/v1/me"))


def _response_headers(
    request: Request, headers: Mapping[str, str] | None = None, *, auth: bool = False
) -> dict[str, str]:
    result = MutableHeaders(headers=headers)
    set_api_response_headers(result, request.scope["path"])
    if auth:
        result["Cache-Control"] = "no-store"
    # State survives middleware ContextVar reset, including unhandled 500s.
    request_id = getattr(request.state, "request_id", None)
    result["X-Request-ID"] = sanitize_request_id(
        request_id or result.get("X-Request-ID") or request.headers.get("X-Request-ID")
    )
    return dict(result)


def _error_envelope(code: str, message: str) -> dict:
    """Build the stable JSON error shape used across all handlers."""
    return {"error": {"code": code, "message": message}}


def request_too_large_response(request: Request) -> JSONResponse:
    headers = MutableHeaders(headers=_response_headers(request, auth=True))
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = "no-referrer"
    return JSONResponse(
        status_code=413,
        content=_error_envelope("REQUEST_TOO_LARGE", "Request too large."),
        headers=dict(headers),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register generic, safe exception handlers on the FastAPI app."""

    @app.exception_handler(FinancialError)
    async def financial_exception_handler(request: Request, exc: FinancialError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(exc.code, exc.message),
            headers=_response_headers(request),
        )

    @app.exception_handler(ConnectionError)
    async def connection_exception_handler(request: Request, exc: ConnectionError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(exc.code, exc.message),
            headers=_response_headers(request),
        )

    @app.exception_handler(ResourceUnavailable)
    async def resource_unavailable_handler(
        request: Request, exc: ResourceUnavailable
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_error_envelope(exc.code, exc.message),
            headers=_response_headers(request, auth=True),
        )

    @app.exception_handler(AuthError)
    async def auth_exception_handler(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(exc.code, exc.message),
            headers=_response_headers(request, exc.headers, auth=True),
        )

    # Registered on starlette.exceptions.HTTPException (the base class), not
    # fastapi.HTTPException (a subclass). Route-not-found 404s are raised by
    # Starlette's router as the BASE class, so registering only on FastAPI's
    # subclass would silently miss them (exception-handler lookup walks the
    # raised exception's MRO, which does not include child classes). This
    # single registration correctly catches both the base class and
    # fastapi.HTTPException raised from within route handlers.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Preserve B0 status/envelope, but never echo caller-supplied exception
        # detail: it may contain provider responses, credentials, or SQL binds.
        try:
            message = HTTPStatus(exc.status_code).phrase
        except ValueError:
            message = "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(code="HTTP_ERROR", message=message),
            headers=_response_headers(request, exc.headers),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        code = "VALIDATION_ERROR"
        if _is_auth_request(request):
            # Inspect only validation categories, never log errors()/body/input.
            types = {error["type"] for error in exc.errors()}
            if "json_invalid" in types:
                code = "MALFORMED_REQUEST"
            elif types == {"invalid_phone"}:
                code = "INVALID_PHONE"
        if request.scope["path"].startswith(
            (
                "/api/v1/connections",
                "/api/v1/commitments",
                "/api/v1/repayments",
                "/api/v1/extension-requests",
                "/api/v1/notifications",
                "/api/v1/notification-preferences",
                "/api/v1/summary",
            )
        ):
            if any(error["type"] == "json_invalid" for error in exc.errors()):
                code = "MALFORMED_REQUEST"
        if request.scope["path"].startswith("/api/v1/commitments") and code != "MALFORMED_REQUEST":
            if request.scope["path"].endswith("/repayments") and any(
                error["loc"] == ("body", "amount_minor") for error in exc.errors()
            ):
                return await financial_exception_handler(request, FinancialError("INVALID_AMOUNT"))
            if not request.scope["path"].endswith(("/repayments", "/extension-requests")) and any(
                error["loc"] == ("body", "principal_amount_minor") for error in exc.errors()
            ):
                return await financial_exception_handler(request, FinancialError("INVALID_AMOUNT"))
        status_code, message = AUTH_ERRORS[code]
        return JSONResponse(
            status_code=status_code,
            content=_error_envelope(code, message),
            headers=_response_headers(request),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Exception strings/tracebacks can contain credentials, bodies, or SQL binds.
        logger.error("Unhandled exception while processing request")
        return JSONResponse(
            status_code=500,
            content=_error_envelope(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred.",
            ),
            headers=_response_headers(request),
        )
