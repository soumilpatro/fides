"""Shared pytest fixtures for FIDES backend tests.

B0: a plain FastAPI TestClient fixture.

B1 adds:
- `db_engine`: a session-scoped engine bound to `TEST_DATABASE_URL` — the
  dedicated, isolated test database (never the development database),
  per the approved B1 test-database decision.
- `db_session`: a per-test session that runs inside an outer transaction
  which is always rolled back at the end of the test (the approved B1
  per-test isolation mechanism), so tests never leave data behind or
  interfere with each other.
- `client`: overrides the app's `get_db` dependency so that requests made
  through the TestClient use the same per-test transactional session as
  `db_session`, keeping route-level and direct-session assertions
  consistent within a single test.

No additional DB-specific test dependency is used (e.g. testcontainers,
pytest-postgresql) — per the approved B1 decision, tests assume the
`db` Postgres container from docker-compose.yml (with its `fides_test`
database) is already running and reachable via `TEST_DATABASE_URL`.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.session import get_db
from app.main import create_app


@pytest.fixture(scope="session")
def db_engine():
    """Engine bound to the dedicated test database (TEST_DATABASE_URL).

    Session-scoped: one engine for the whole test run. Never points at
    the same database as the application's own DATABASE_URL.
    """
    settings = get_settings()
    if not settings.test_database_url:
        pytest.skip(
            "TEST_DATABASE_URL is not configured; skipping tests that require "
            "the dedicated test database."
        )
    engine = create_engine(settings.test_database_url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """A database session scoped to a single test, always rolled back.

    Implements the approved B1 per-test isolation mechanism: the outer
    transaction started here is rolled back after the test, regardless
    of what the test itself committed or rolled back internally.

    Uses SQLAlchemy's recommended "join an external transaction with a
    SAVEPOINT" pattern (`join_transaction_mode="create_savepoint"`): if a
    test calls `session.rollback()` itself (e.g. after catching an
    IntegrityError from a constraint test), only the inner SAVEPOINT is
    rolled back, leaving the outer transaction intact for this fixture's
    own teardown to roll back.
    """
    connection = db_engine.connect()
    outer_transaction = connection.begin()
    session_factory = sessionmaker(
        bind=connection, future=True, join_transaction_mode="create_savepoint"
    )
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        if outer_transaction.is_active:
            outer_transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient whose `get_db` dependency yields the per-test session.

    Any route hit through this client — including `/health` and
    `/readiness` — participates in the same transactional, auto-rolled-back
    session as `db_session`, so a test can freely mix direct-session
    assertions and API calls without them seeing different data.
    """
    app = create_app()

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
