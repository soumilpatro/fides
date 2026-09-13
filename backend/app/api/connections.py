"""The seven approved B4-D0 endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.auth import AuthErrorEnvelope, get_auth_service, require_empty_body
from app.api.auth import router as auth_router
from app.api.auth_schemas import EmptyAuthRequest
from app.api.connection_schemas import ConnectionRequest, ConnectionResponse
from app.api.dependencies import require_principal
from app.auth.sessions import Principal
from app.connections import ConnectionService

RESPONSE_HEADERS = {
    "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
    "X-Request-ID": {"schema": {"type": "string"}},
}
EMPTY_BODY = {
    "requestBody": {
        "required": False,
        "content": {"application/json": {"schema": EmptyAuthRequest.model_json_schema()}},
    }
}

router = APIRouter(
    prefix="/api/v1/connections",
    tags=["Connections"],
    responses={
        **{status: spec for status, spec in auth_router.responses.items() if status != 429},
        404: {"model": AuthErrorEnvelope, "headers": RESPONSE_HEADERS},
    },
)


def get_connection_service(service=Depends(get_auth_service)):
    return ConnectionService(service.session_service)


@router.post(
    "",
    status_code=201,
    response_model=ConnectionResponse,
    responses={201: {"headers": RESPONSE_HEADERS}},
)
async def create_connection(
    body: ConnectionRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_connection_service),
):
    return await run_in_threadpool(
        service.create, principal, body, request_id=request.state.request_id
    )


@router.get(
    "", response_model=list[ConnectionResponse], responses={200: {"headers": RESPONSE_HEADERS}}
)
async def list_connections(
    principal: Principal = Depends(require_principal), service=Depends(get_connection_service)
):
    return await run_in_threadpool(service.list, principal)


@router.get(
    "/{id}", response_model=ConnectionResponse, responses={200: {"headers": RESPONSE_HEADERS}}
)
async def detail_connection(
    id: UUID,
    principal: Principal = Depends(require_principal),
    service=Depends(get_connection_service),
):
    return await run_in_threadpool(service.detail, principal, id)


@router.post(
    "/{id}/accept",
    response_model=ConnectionResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=EMPTY_BODY,
)
async def accept_connection(
    id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_connection_service),
):
    await require_empty_body(request)
    return await run_in_threadpool(
        service.mutate, principal, id, "accept", request_id=request.state.request_id
    )


@router.post(
    "/{id}/reject",
    response_model=ConnectionResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=EMPTY_BODY,
)
async def reject_connection(
    id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_connection_service),
):
    await require_empty_body(request)
    return await run_in_threadpool(
        service.mutate, principal, id, "reject", request_id=request.state.request_id
    )


@router.post(
    "/{id}/block",
    response_model=ConnectionResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=EMPTY_BODY,
)
async def block_connection(
    id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_connection_service),
):
    await require_empty_body(request)
    return await run_in_threadpool(
        service.mutate, principal, id, "block", request_id=request.state.request_id
    )


@router.delete(
    "/{id}",
    response_model=ConnectionResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=EMPTY_BODY,
)
async def remove_connection(
    id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_connection_service),
):
    await require_empty_body(request)
    return await run_in_threadpool(
        service.mutate, principal, id, "remove", request_id=request.state.request_id
    )
