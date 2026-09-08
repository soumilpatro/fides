"""Health and readiness endpoints (B0 foundation, extended in B1).

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

B1 extends `/readiness` to verify database connectivity, per B0's own
stated intent ("This will be extended starting B1 to verify database
connectivity once persistence is introduced"). No connection string,
credential, or query result is ever exposed in the response body.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db

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
def readiness(db: Session = Depends(get_db)) -> dict:
    """Readiness check: process is up AND the database is reachable.

    Runs a trivial `SELECT 1` to confirm connectivity through the
    connection pool. Never returns the database URL, credentials, or
    any query result — only a boolean-shaped status.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return {"status": "not_ready", "database": "unreachable"}

    return {"status": "ready", "database": "reachable"}
