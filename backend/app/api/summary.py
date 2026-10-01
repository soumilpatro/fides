"""The sole approved B12 endpoint; no body, filters, or pagination."""

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.connections import RESPONSE_HEADERS
from app.api.dependencies import require_principal
from app.api.ledger import router as ledger_router
from app.api.summary_schemas import SummaryResponse
from app.auth.sessions import Principal
from app.core.errors import AuthError
from app.summary import SummaryService

router = APIRouter(
    prefix="/api/v1/summary",
    tags=["Summary"],
    responses={k: v for k, v in ledger_router.responses.items() if k != 404},
)


def get_summary_service(service=Depends(get_auth_service)):
    return SummaryService(service.session_service)


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
