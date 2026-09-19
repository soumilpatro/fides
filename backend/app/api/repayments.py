"""Exactly the three approved B7 reporting/read endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.commitments import IDEMPOTENCY_PARAMETER, idempotency_key
from app.api.connections import RESPONSE_HEADERS
from app.api.connections import router as connection_router
from app.api.dependencies import require_principal
from app.api.repayment_schemas import RepaymentRequest, RepaymentResponse
from app.auth.sessions import Principal
from app.repayments import RepaymentService

router = APIRouter(
    prefix="/api/v1",
    tags=["Repayments"],
    responses={
        **connection_router.responses,
        400: {**connection_router.responses[400], "description": "MALFORMED_REQUEST"},
        403: {
            **connection_router.responses[403],
            "description": "FORBIDDEN or account unavailable",
        },
        409: {
            **connection_router.responses[409],
            "description": "INVALID_STATE, OVER_REPAYMENT, CONFLICT, IDEMPOTENCY_CONFLICT",
        },
        422: {
            **connection_router.responses[422],
            "description": "CURRENCY_MISMATCH, INVALID_AMOUNT, VALIDATION_ERROR",
        },
    },
)


def get_repayment_service(service=Depends(get_auth_service)):
    return RepaymentService(service.session_service)


@router.post(
    "/commitments/{id}/repayments",
    status_code=201,
    response_model=RepaymentResponse,
    responses={201: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def report_repayment(
    id: UUID,
    body: RepaymentRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_repayment_service),
):
    status, result = await run_in_threadpool(
        service.create, principal, id, body, key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.get(
    "/commitments/{id}/repayments",
    response_model=list[RepaymentResponse],
    responses={200: {"headers": RESPONSE_HEADERS}},
)
async def list_repayments(
    id: UUID,
    principal: Principal = Depends(require_principal),
    service=Depends(get_repayment_service),
):
    return await run_in_threadpool(service.read, principal, id)


@router.get(
    "/repayments/{id}",
    response_model=RepaymentResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
)
async def detail_repayment(
    id: UUID,
    principal: Principal = Depends(require_principal),
    service=Depends(get_repayment_service),
):
    return await run_in_threadpool(service.read, principal, id, detail=True)
