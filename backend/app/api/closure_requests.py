"""Six approved closure routes with existing auth and idempotency conventions."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.auth_schemas import EmptyAuthRequest
from app.api.closure_schemas import ClosureRequestCreate, ClosureResponse
from app.api.commitments import IDEMPOTENCY_PARAMETER, idempotency_key
from app.api.connections import RESPONSE_HEADERS
from app.api.dependencies import require_principal
from app.api.extensions import router as extension_router
from app.auth.sessions import Principal
from app.mutual_closure import MutualClosureService

router = APIRouter(prefix="/api/v1", tags=["Mutual Closure"], responses=extension_router.responses)


def get_closure_service(service=Depends(get_auth_service)):
    return MutualClosureService(service.session_service)


@router.post(
    "/commitments/{id}/closure-requests",
    status_code=201,
    response_model=ClosureResponse,
    responses={201: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def create(
    id: UUID,
    body: ClosureRequestCreate,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_closure_service),
):
    status, result = await run_in_threadpool(
        service.create, principal, id, body, key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.get(
    "/commitments/{id}/closure-requests",
    response_model=list[ClosureResponse],
    responses={200: {"headers": RESPONSE_HEADERS}},
)
async def list_requests(
    id: UUID,
    principal: Principal = Depends(require_principal),
    service=Depends(get_closure_service),
):
    return await run_in_threadpool(service.list, principal, id)


@router.get(
    "/closure-requests/{id}",
    response_model=ClosureResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
)
async def detail(
    id: UUID,
    principal: Principal = Depends(require_principal),
    service=Depends(get_closure_service),
):
    return await run_in_threadpool(service.detail, principal, id)


@router.post(
    "/closure-requests/{id}/accept",
    response_model=ClosureResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def accept(
    id: UUID,
    body: EmptyAuthRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_closure_service),
):
    status, result = await run_in_threadpool(
        service.decide, principal, id, "accept", key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.post(
    "/closure-requests/{id}/reject",
    response_model=ClosureResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def reject(
    id: UUID,
    body: EmptyAuthRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_closure_service),
):
    status, result = await run_in_threadpool(
        service.decide, principal, id, "reject", key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)


@router.post(
    "/closure-requests/{id}/cancel",
    response_model=ClosureResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    openapi_extra=IDEMPOTENCY_PARAMETER,
)
async def cancel(
    id: UUID,
    body: EmptyAuthRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    key: str = Depends(idempotency_key),
    service=Depends(get_closure_service),
):
    status, result = await run_in_threadpool(
        service.decide, principal, id, "cancel", key, request_id=request.state.request_id
    )
    return JSONResponse(status_code=status, content=result)
