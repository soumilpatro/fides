"""The four approved B2-C HTTP endpoints; account profile routes are B2-D."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBearer
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.auth_schemas import (
    AuthSchema,
    CredentialResponse,
    EmptyAuthRequest,
    LogoutResponse,
    OtpRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
    RefreshRequest,
)
from app.auth.challenges import ChallengeService
from app.auth.providers import build_provider
from app.auth.rate_limits import client_ip
from app.config import get_settings
from app.core.errors import AuthError
from app.db.session import get_sessionmaker


class AuthErrorDetail(AuthSchema):
    code: str
    message: str


class AuthErrorEnvelope(AuthSchema):
    error: AuthErrorDetail


router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Authentication"],
    responses={
        status: {
            "model": AuthErrorEnvelope,
            "headers": {
                "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
                "X-Request-ID": {"schema": {"type": "string"}},
                **(
                    {"WWW-Authenticate": {"schema": {"type": "string", "const": "Bearer"}}}
                    if status == 401
                    else {}
                ),
                **(
                    {"Retry-After": {"schema": {"type": "integer", "minimum": 0}}}
                    if status == 429
                    else {}
                ),
            },
        }
        for status in (400, 401, 403, 409, 422, 429, 500, 503)
    },
)
bearer = HTTPBearer(auto_error=False)


def authorization_header(request: Request) -> str | None:
    values = request.headers.getlist("Authorization")
    if len(values) > 1:
        raise AuthError("INVALID_AUTH_TOKEN")
    return values[0] if values else None


async def require_empty_body(request: Request):
    # Absence and {} are accepted; explicit JSON null is not an empty object.
    raw = await request.body()
    if raw:
        try:
            EmptyAuthRequest.model_validate_json(raw)
        except ValidationError as error:
            code = (
                "MALFORMED_REQUEST"
                if any(item["type"] == "json_invalid" for item in error.errors())
                else "VALIDATION_ERROR"
            )
            raise AuthError(code) from None


def get_auth_service(request: Request) -> ChallengeService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise AuthError("AUTH_PROVIDER_UNAVAILABLE")
    return service


def get_client_ip(request: Request) -> str:
    if request.client is None:
        raise AuthError("SERVICE_UNAVAILABLE")
    try:
        return client_ip(
            request.client.host,
            request.headers.get("X-Forwarded-For"),
            trusted_proxies=get_settings().auth_trusted_proxy_cidrs,
        )
    except ValueError:
        raise AuthError("MALFORMED_REQUEST") from None


async def verify_ip_budget(service=Depends(get_auth_service), ip=Depends(get_client_ip)):
    await run_in_threadpool(service.limiter.otp_verify, ip=ip)


def initialize_auth(app):
    """One pooled provider client per lifespan, with no network activity at startup."""
    settings = get_settings()
    if settings.otp_provider == "disabled":
        app.state.auth_service = None
        return
    app.state.auth_service = ChallengeService(
        get_sessionmaker(), settings, build_provider(settings)
    )


@router.post("/otp/request", status_code=202, response_model=OtpRequestResponse)
async def request_otp(
    body: OtpRequest, request: Request, service=Depends(get_auth_service), ip=Depends(get_client_ip)
):
    return await service.request(body, ip=ip, request_id=request.state.request_id)


@router.post(
    "/otp/verify", response_model=CredentialResponse, dependencies=[Depends(verify_ip_budget)]
)
async def verify_otp(body: OtpVerifyRequest, request: Request, service=Depends(get_auth_service)):
    return await service.verify(body, request_id=request.state.request_id)


@router.post("/refresh", response_model=CredentialResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    service=Depends(get_auth_service),
    ip=Depends(get_client_ip),
):
    return await run_in_threadpool(
        service.session_service.refresh,
        body.refresh_token,
        ip=ip,
        request_id=request.state.request_id,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    openapi_extra={
        "requestBody": {
            "required": False,
            "content": {"application/json": {"schema": EmptyAuthRequest.model_json_schema()}},
        }
    },
)
async def logout(
    request: Request,
    service=Depends(get_auth_service),
    _bearer: Annotated[object, Depends(bearer)] = None,
):
    await require_empty_body(request)
    recognition = await run_in_threadpool(
        service.session_service.recognize_logout,
        authorization_header(request),
    )
    await run_in_threadpool(
        service.session_service.revoke_one, recognition, request_id=request.state.request_id
    )
    return LogoutResponse(logged_out=True)
