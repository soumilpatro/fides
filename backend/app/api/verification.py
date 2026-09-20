"""The three B8-D0 endpoints, with existing B7 repayment responses."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.commitments import IDEMPOTENCY_PARAMETER, idempotency_key
from app.api.connections import RESPONSE_HEADERS
from app.api.connections import router as connection_router
from app.api.dependencies import require_principal
from app.api.repayment_schemas import RepaymentResponse
from app.api.verification_schemas import DecisionRequest, VerificationResponse
from app.auth.sessions import Principal
from app.verification import VerificationService

router = APIRouter(
    prefix="/api/v1/repayments",
    tags=["Verification"],
    responses={
        **connection_router.responses,
        409: {
            **connection_router.responses[409],
            "description": (
                "INVALID_STATE, ALREADY_VERIFIED, OVER_REPAYMENT, IDEMPOTENCY_CONFLICT, CONFLICT"
            ),
        },
        422: {**connection_router.responses[422], "description": "VALIDATION_ERROR"},
    },
)


def get_verification_service(service=Depends(get_auth_service)):
    return VerificationService(service.session_service)


@router.post(
    "/{id}/verify",
    response_model=RepaymentResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def verify(
    id: UUID,
    body: DecisionRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_verification_service),
):
    status, result = await run_in_threadpool(
        service.decide, principal, id, "verify", body, key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.post(
    "/{id}/dispute",
    response_model=RepaymentResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def dispute(
    id: UUID,
    body: DecisionRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_verification_service),
):
    status, result = await run_in_threadpool(
        service.decide, principal, id, "dispute", body, key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.get(
    "/{id}/verification-history",
    response_model=list[VerificationResponse],
    responses={200: {"headers": RESPONSE_HEADERS}},
)
async def history(
    id: UUID,
    principal: Principal = Depends(require_principal),
    service=Depends(get_verification_service),
):
    return await run_in_threadpool(service.history, principal, id)
