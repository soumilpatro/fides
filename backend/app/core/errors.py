"""Consistent error-handling foundation for the FIDES backend (B0 scope).

Provides a uniform JSON error envelope and exception handlers so that:
- HTTPExceptions (e.g. 404 on an unknown route) return a stable shape.
- Unhandled exceptions never leak stack traces or internals to the client,
  per API Specification Sec. 10 ("Never expose stack traces or secrets")
  and Tech Specification Sec. 22/23.

This is deliberately generic. Domain-specific error codes defined in the
API Specification (Sec. 10: AUTH_REQUIRED, FORBIDDEN, INVALID_AMOUNT,
OVER_REPAYMENT, IDEMPOTENCY_CONFLICT, etc.) are NOT implemented here — they
belong to the phases that introduce the corresponding domain behaviour
(B2+ auth, B5+ commitments/repayments). Introducing them now would be
scope creep beyond B0's "consistent error handling ... foundations" item.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("fides.errors")


def _error_envelope(code: str, message: str) -> dict:
    """Build the stable JSON error shape used across all handlers."""
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    """Register generic, safe exception handlers on the FastAPI app."""

    # Registered on starlette.exceptions.HTTPException (the base class), not
    # fastapi.HTTPException (a subclass). Route-not-found 404s are raised by
    # Starlette's router as the BASE class, so registering only on FastAPI's
    # subclass would silently miss them (exception-handler lookup walks the
    # raised exception's MRO, which does not include child classes). This
    # single registration correctly catches both the base class and
    # fastapi.HTTPException raised from within route handlers.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(code="HTTP_ERROR", message=str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_envelope(
                code="VALIDATION_ERROR", message="Request validation failed."
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Log full details server-side only; never return internals to the client.
        logger.exception("Unhandled exception while processing request")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_envelope(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred.",
            ),
        )
