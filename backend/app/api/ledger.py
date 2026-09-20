"""The sole public B9 read endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.connections import RESPONSE_HEADERS
from app.api.connections import router as connection_router
from app.api.dependencies import require_principal
from app.api.ledger_schemas import LedgerResponse
from app.auth.sessions import Principal
from app.core.errors import AuthError
from app.ledger import LedgerService

router = APIRouter(
    prefix="/api/v1/commitments",
    tags=["Ledger"],
    responses={
        code: {**spec, **({"description": description} if description else {})}
        for code, spec in connection_router.responses.items()
        if code != 409
        for description in [
            {404: "NOT_FOUND", 422: "VALIDATION_ERROR", 503: "SERVICE_UNAVAILABLE"}.get(code)
        ]
    },
)


def get_ledger_service(service=Depends(get_auth_service)):
    return LedgerService(service.session_service)


@router.get(
    "/{id}/ledger",
    response_model=LedgerResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    description="Live keyset timeline ordered by occurred_at then id; no cross-page snapshot.",
)
async def ledger(
    id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    service=Depends(get_ledger_service),
):
    # Match FastAPI's last-value handling for repeated scalar query parameters.
    # Reject float spellings that Pydantic otherwise coerces to integers.
    raw_limit = request.query_params.get("limit", "50")
    if not raw_limit.isascii() or not raw_limit.isdecimal():
        raise AuthError("VALIDATION_ERROR")
    return await run_in_threadpool(service.list, principal, id, limit, cursor)
