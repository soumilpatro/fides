"""FastAPI application factory/entrypoint for the FIDES backend.

B0 scope (per AI Development & Backend Build Specification Sec. 9):
- Application factory
- Health/readiness endpoints
- Consistent error handling
- Request correlation / structured logging

No domain routers (auth, connections, commitments, repayments, ledger,
extensions, notifications, summaries) are wired in at this stage. Those
are introduced starting B2/B4 per the build order.
"""

from fastapi import FastAPI

from app.api.health import router as health_router
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

    app = FastAPI(
        title=settings.app_name,
        description=(
            "FIDES shared backend. See FIDES_TECH_SPECIFICATION_v1.1 and "
            "FIDES_API_SPECIFICATION_v1.0 for the full product/API contract. "
            "This build currently implements B0 (repository/bootstrap) only."
        ),
    )

    app.add_middleware(RequestCorrelationMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router)

    return app


app = create_app()
