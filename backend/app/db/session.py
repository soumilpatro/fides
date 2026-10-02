"""Database engine and session management (B1 scope).

Provides:
- A pooled SQLAlchemy engine bound to `Settings.database_url`.
- A `sessionmaker` for creating sessions.
- A FastAPI dependency (`get_db`) that yields one session per request and
  guarantees it is closed afterward.

No query or repository logic lives here. Domain services introduced
starting B5 will depend on `get_db`; B1 itself does not use it in any
route beyond the readiness check.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _build_engine():
    settings = get_settings()
    return create_engine(
        settings.database_url,
        isolation_level=settings.database_isolation_level,
        pool_pre_ping=True,  # detect and discard stale/dropped connections
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        future=True,
        hide_parameters=True,  # SQL exceptions must not expose credential/PII bind values.
    )


# Module-level engine/session factory. Created lazily on first access via
# get_engine()/get_sessionmaker() rather than at import time, so importing
# this module never requires DATABASE_URL to already be configured (e.g.
# during test collection before fixtures override settings).
_engine = None
_SessionLocal = None


def get_engine():
    """Return the process-wide SQLAlchemy engine, creating it if needed."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_sessionmaker() -> sessionmaker:
    """Return the process-wide session factory, creating it if needed."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            future=True,
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session per request.

    The session is always closed after the request, regardless of
    whether the request succeeded or raised. No commit/rollback policy
    beyond that is imposed here — that belongs to the service layer
    introduced starting B5+, which owns transaction boundaries for
    financial mutations.
    """
    session_factory = get_sessionmaker()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
