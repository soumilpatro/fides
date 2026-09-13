"""FastAPI application factory/entrypoint for the FIDES backend.

B0 scope (per AI Development & Backend Build Specification Sec. 9):
- Application factory
- Health/readiness endpoints
- Consistent error handling
- Request correlation / structured logging

B2 adds the seven approved authentication/account endpoints and a provider
client owned by the application lifespan.

Launch Uvicorn with --no-proxy-headers: Fides resolves forwarding headers
against AUTH_TRUSTED_PROXY_CIDRS and needs the original connection peer.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import initialize_auth
from app.api.auth import router as auth_router
from app.api.commitments import router as commitments_router
from app.api.connections import router as connections_router
from app.api.health import router as health_router
from app.api.me import router as me_router
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestCorrelationMiddleware, configure_logging


def create_app() -> FastAPI:
    """Application factory.

    Building the app behind a factory function (rather than a bare
    module-level `app = FastAPI()` with routes attached ad hoc) keeps
    startup deterministic and testable, and gives later phases (B1+) a
    single place to wire in database sessions, auth, and domain routers
    without restructuring this module.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app):
        initialize_auth(app)
        try:
            yield
        finally:
            if app.state.auth_service is not None:
                await app.state.auth_service.provider.aclose()

    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        description=(
            "FIDES shared backend. See FIDES_TECH_SPECIFICATION_v1.1 and "
            "FIDES_API_SPECIFICATION_v1.0 for the full product/API contract. "
            "Includes OTP authentication, sessions, profile updates and account deactivation."
        ),
    )

    app.add_middleware(RequestCorrelationMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(connections_router)
    app.include_router(commitments_router)

    return app


app = create_app()
