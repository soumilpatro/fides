"""The two approved B6 read routes; initial terms use existing B5 creation."""

from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.connections import RESPONSE_HEADERS
from app.api.connections import router as connection_router
from app.api.dependencies import require_principal
from app.api.term_schemas import InstallmentResponse, TermsResponse
from app.auth.sessions import Principal
from app.terms import TermsService

router = APIRouter(
    prefix="/api/v1/commitments", tags=["Terms"], responses=connection_router.responses
)


def get_terms_service(service=Depends(get_auth_service)):
    return TermsService(service.session_service)


@router.get(
    "/{id}/terms", response_model=TermsResponse, responses={200: {"headers": RESPONSE_HEADERS}}
)
async def read_terms(
    id: UUID, principal: Principal = Depends(require_principal), service=Depends(get_terms_service)
):
    return await run_in_threadpool(service.read, principal, id)


@router.get(
    "/{id}/installments",
    response_model=list[InstallmentResponse],
    responses={200: {"headers": RESPONSE_HEADERS}},
)
async def read_installments(
    id: UUID, principal: Principal = Depends(require_principal), service=Depends(get_terms_service)
):
    return await run_in_threadpool(service.read, principal, id, installments=True)
