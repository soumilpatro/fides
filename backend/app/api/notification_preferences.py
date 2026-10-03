"""Authenticated current-user reminder settings."""

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.auth import get_auth_service
from app.api.connections import RESPONSE_HEADERS
from app.api.dependencies import require_principal
from app.api.ledger import router as ledger_router
from app.api.notification_preference_schemas import NotificationPreferences
from app.auth.sessions import Principal
from app.core.errors import AuthError
from app.notification_preferences import PreferenceService

router = APIRouter(
    prefix="/api/v1/notification-preferences",
    tags=["Notification Preferences"],
    responses=ledger_router.responses,
)


def get_preference_service(service=Depends(get_auth_service)):
    return PreferenceService(service.session_service)


def no_query(request):
    if request.query_params:
        raise AuthError("VALIDATION_ERROR")


@router.get(
    "", response_model=NotificationPreferences, responses={200: {"headers": RESPONSE_HEADERS}}
)
async def read_preferences(
    request: Request,
    principal: Principal = Depends(require_principal),
    service=Depends(get_preference_service),
):
    no_query(request)
    return await run_in_threadpool(service.read, principal)


@router.post(
    "", response_model=NotificationPreferences, responses={200: {"headers": RESPONSE_HEADERS}}
)
async def write_preferences(
    request: Request,
    body: NotificationPreferences,
    principal: Principal = Depends(require_principal),
    service=Depends(get_preference_service),
):
    no_query(request)
    return await run_in_threadpool(service.write, principal, body)
