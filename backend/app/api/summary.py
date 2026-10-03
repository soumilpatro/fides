"""B12 currency summary and bounded Upcoming/Overdue occurrence reads."""

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.connections import RESPONSE_HEADERS
from app.api.dependencies import require_principal
from app.api.ledger import router as ledger_router
from app.api.summary_schemas import OccurrenceResponse, SummaryResponse
from app.auth.sessions import Principal
from app.core.errors import AuthError
from app.summary import SummaryService
from app.summary_occurrences import OccurrenceService

router = APIRouter(
    prefix="/api/v1/summary",
    tags=["Summary"],
    responses={k: v for k, v in ledger_router.responses.items() if k != 404},
)


def get_summary_service(service=Depends(get_auth_service)):
    return SummaryService(service.session_service)


def get_occurrence_service(service=Depends(get_auth_service)):
    return OccurrenceService(service.session_service)


@router.get(
    "",
    response_model=SummaryResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    description="Current verified outstanding per currency for the authenticated participant.",
)
async def summary(
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_summary_service),
):
    if request.query_params or await request.body():
        raise AuthError("VALIDATION_ERROR")
    return await run_in_threadpool(service.read, principal)


async def _occurrences(request, principal, service, kind, limit, cursor):
    raw = request.query_params.get("limit", "50")
    if not raw.isascii() or not raw.isdecimal() or await request.body():
        raise AuthError("VALIDATION_ERROR")
    return await run_in_threadpool(service.list, principal, kind, limit, cursor)


@router.get(
    "/upcoming",
    response_model=OccurrenceResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    description="Upcoming — next 7 days. Live, bounded schedule occurrences.",
)
async def upcoming(
    request: Request,
    principal: Principal = Depends(require_principal),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    service=Depends(get_occurrence_service),
):
    return await _occurrences(request, principal, service, "UPCOMING", limit, cursor)


@router.get(
    "/overdue",
    response_model=OccurrenceResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    description="Live overdue schedule occurrences; no financial or lifecycle side effects.",
)
async def overdue(
    request: Request,
    principal: Principal = Depends(require_principal),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    service=Depends(get_occurrence_service),
):
    return await _occurrences(request, principal, service, "OVERDUE", limit, cursor)
