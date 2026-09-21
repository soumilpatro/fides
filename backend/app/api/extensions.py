"""The four approved B10-D0 routes. Decisions require a closed JSON object."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.auth_schemas import EmptyAuthRequest
from app.api.commitments import IDEMPOTENCY_PARAMETER, idempotency_key
from app.api.connections import RESPONSE_HEADERS
from app.api.connections import router as connection_router
from app.api.dependencies import require_principal
from app.api.extension_schemas import ExtensionRequestBody, ExtensionResponse
from app.auth.sessions import Principal
from app.extensions import ExtensionService

router = APIRouter(
    prefix="/api/v1",
    tags=["Extensions"],
    responses={
        **connection_router.responses,
        409: {
            **connection_router.responses[409],
            "description": "INVALID_STATE, CONFLICT, IDEMPOTENCY_CONFLICT",
        },
        422: {**connection_router.responses[422], "description": "VALIDATION_ERROR"},
        503: {**connection_router.responses[503], "description": "SERVICE_UNAVAILABLE"},
    },
)


def get_extension_service(service=Depends(get_auth_service)):
    return ExtensionService(service.session_service)


@router.post(
    "/commitments/{id}/extension-requests",
    status_code=201,
    response_model=ExtensionResponse,
    responses={201: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def create(
    id: UUID,
    body: ExtensionRequestBody,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_extension_service),
):
    status, result = await run_in_threadpool(
        service.create, principal, id, body, key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.get(
    "/commitments/{id}/extension-requests",
    response_model=list[ExtensionResponse],
    responses={200: {"headers": RESPONSE_HEADERS}},
)
async def list_requests(
    id: UUID,
    principal: Principal = Depends(require_principal),
    service=Depends(get_extension_service),
):
    return await run_in_threadpool(service.list, principal, id)


@router.post(
    "/extension-requests/{id}/accept",
    response_model=ExtensionResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def accept(
    id: UUID,
    body: EmptyAuthRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_extension_service),
):
    status, result = await run_in_threadpool(
        service.decide, principal, id, "accept", key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.post(
    "/extension-requests/{id}/reject",
    response_model=ExtensionResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def reject(
    id: UUID,
    body: EmptyAuthRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_extension_service),
):
    status, result = await run_in_threadpool(
        service.decide, principal, id, "reject", key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)
