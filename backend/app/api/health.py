"""Health and readiness endpoints (B0 scope).

Exposed as unversioned infrastructure routes (`/health`, `/readiness`)
rather than under `/api/v1`, since the API Specification's `/api/v1`
surface is reserved for the domain contract (auth, connections,
commitments, repayments, etc.) and health probes conventionally sit
outside versioned business APIs. This convention was flagged to the
product owner prior to implementation as a naming precedent for later
phases.

Neither endpoint exposes configuration values, secrets, or internals —
only static/non-sensitive status fields, per AI Build Spec B0 item:
"Add health/readiness endpoints without exposing secrets."
"""

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["infrastructure"])


@router.get("/health")
def health() -> dict:
    """Liveness check: process is up and able to handle requests."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
    }


@router.get("/readiness")
def readiness() -> dict:
    """Readiness check.

    At B0 there are no external dependencies (database, etc.) to verify,
    so readiness is equivalent to liveness. This will be extended starting
    B1 to verify database connectivity once persistence is introduced.
    """
    return {"status": "ready"}
