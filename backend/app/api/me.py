"""The three approved account endpoints; services own all transaction boundaries."""

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service, require_empty_body
from app.api.auth import router as auth_router
from app.api.auth_schemas import (
    DeactivationResponse,
    EmptyAuthRequest,
    MeResponse,
    ProfileUpdateRequest,
)
from app.api.dependencies import require_principal
from app.auth.accounts import AccountService
from app.auth.sessions import Principal

router = APIRouter(prefix="/api/v1/me", tags=["Account"], responses=auth_router.responses)


def get_account_service(service=Depends(get_auth_service)) -> AccountService:
    return AccountService(service.session_service)


@router.get("", response_model=MeResponse)
async def get_me(
    principal: Principal = Depends(require_principal), service=Depends(get_account_service)
):
    return await run_in_threadpool(service.get, principal)


@router.patch("", response_model=MeResponse)
async def patch_me(
    body: ProfileUpdateRequest,
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_account_service),
):
    return await run_in_threadpool(
        service.update, principal, body, request_id=request.state.request_id
    )


@router.post(
    "/deactivate",
    response_model=DeactivationResponse,
    openapi_extra={
        "requestBody": {
            "required": False,
            "content": {"application/json": {"schema": EmptyAuthRequest.model_json_schema()}},
        }
    },
)
async def deactivate_me(
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_account_service),
):
    await require_empty_body(request)
    return await run_in_threadpool(
        service.deactivate, principal, request_id=request.state.request_id
    )
