"""The two approved B11 in-app inbox endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.auth_schemas import EmptyAuthRequest
from app.api.connections import RESPONSE_HEADERS
from app.api.dependencies import require_principal
from app.api.ledger import router as ledger_router
from app.api.notification_schemas import NotificationListResponse, NotificationResponse
from app.auth.sessions import Principal
from app.core.errors import AuthError
from app.notifications import NotificationService

router = APIRouter(
    prefix="/api/v1/notifications", tags=["Notifications"], responses=ledger_router.responses
)


def get_notification_service(service=Depends(get_auth_service)):
    return NotificationService(service.session_service)


@router.get(
    "",
    response_model=NotificationListResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
    description="Recipient inbox, created_at DESC then id DESC. Live keyset pagination.",
)
async def inbox(
    request: Request,
    principal: Principal = Depends(require_principal),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    service=Depends(get_notification_service),
):
    raw = request.query_params.get("limit", "50")
    if not raw.isascii() or not raw.isdecimal():
        raise AuthError("VALIDATION_ERROR")
    return await run_in_threadpool(service.list, principal, limit, cursor)


@router.post(
    "/{id}/read",
    response_model=NotificationResponse,
    responses={200: {"headers": RESPONSE_HEADERS}},
)
async def mark_read(
    id: UUID,
    body: EmptyAuthRequest,
    principal: Principal = Depends(require_principal),
    service=Depends(get_notification_service),
):
    return await run_in_threadpool(service.mark_read, principal, id)
