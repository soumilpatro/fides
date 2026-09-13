"""Exactly six B5-D1 routes. Replays return the original validated response."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service, require_empty_body
from app.api.commitment_schemas import CommitmentRequest, CommitmentResponse
from app.api.connections import EMPTY_BODY, RESPONSE_HEADERS
from app.api.connections import router as connection_router
from app.api.dependencies import require_principal
from app.auth.sessions import Principal
from app.commitments import CommitmentService
from app.core.errors import AuthError
from app.idempotency import validate_key

IDEMPOTENCY_PARAMETER = {
    "parameters": [
        {
            "in": "header",
            "name": "Idempotency-Key",
            "required": True,
            "schema": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": r"^[A-Za-z0-9._:-]+$",
            },
        }
    ]
}
router = APIRouter(
    prefix="/api/v1/commitments", tags=["Commitments"], responses=connection_router.responses
)


def get_commitment_service(service=Depends(get_auth_service)):
    return CommitmentService(service.session_service)


def idempotency_key(request: Request):
    values = request.headers.getlist("Idempotency-Key")
    if len(values) != 1:
        raise AuthError("MALFORMED_REQUEST")
    return validate_key(values[0])


@router.post(
    "",
    status_code=201,
    response_model=CommitmentResponse,
    responses={201: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def create_commitment(
    body: CommitmentRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_commitment_service),
):
    status, result = await run_in_threadpool(
        service.create, principal, body, key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.get(
    "", response_model=list[CommitmentResponse], responses={200: {"headers": RESPONSE_HEADERS}}
)
async def list_commitments(
    principal: Principal = Depends(require_principal), service=Depends(get_commitment_service)
):
    return await run_in_threadpool(service.list, principal)


@router.get(
    "/{id}", response_model=CommitmentResponse, responses={200: {"headers": RESPONSE_HEADERS}}
)
async def detail_commitment(
    id: UUID,
    principal: Principal = Depends(require_principal),
    service=Depends(get_commitment_service),
):
    return await run_in_threadpool(service.detail, principal, id)


@router.post(
    "/{id}/confirm",
    response_model=CommitmentResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra={**EMPTY_BODY, **IDEMPOTENCY_PARAMETER},
)
async def confirm_commitment(
    id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_commitment_service),
):
    await require_empty_body(request)
    status, result = await run_in_threadpool(
        service.mutate, principal, id, "confirm", key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.post(
    "/{id}/reject",
    response_model=CommitmentResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra={**EMPTY_BODY, **IDEMPOTENCY_PARAMETER},
)
async def reject_commitment(
    id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_commitment_service),
):
    await require_empty_body(request)
    status, result = await run_in_threadpool(
        service.mutate, principal, id, "reject", key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.post(
    "/{id}/cancel",
    response_model=CommitmentResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra={**EMPTY_BODY, **IDEMPOTENCY_PARAMETER},
)
async def cancel_commitment(
    id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_commitment_service),
):
    await require_empty_body(request)
    status, result = await run_in_threadpool(
        service.mutate, principal, id, "cancel", key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)
