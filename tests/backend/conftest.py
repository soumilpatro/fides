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
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.db.session import get_db
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="session")
def db_engine():
    """Engine bound to the dedicated test database (TEST_DATABASE_URL).

    Session-scoped: one engine for the whole test run. Never points at
    the same database as the application's own DATABASE_URL.
    """
    settings = get_settings()
    if not settings.test_database_url:
        pytest.fail("TEST_DATABASE_URL must be configured for the required PostgreSQL suite.")
    test_url = make_url(settings.test_database_url)
    if test_url.get_backend_name() != "postgresql" or test_url.database != "fides_test":
        pytest.fail("Database tests require the dedicated PostgreSQL fides_test database.")
    if settings.database_url and make_url(settings.database_url).database == test_url.database:
        pytest.fail("TEST_DATABASE_URL must be distinct from the development database.")
    engine = create_engine(settings.test_database_url, future=True)
    try:
        # A libpq/query override can change the actual database independently of
        # the URL path. Check the connected database before any migration DDL.
        with engine.connect() as connection:
            if connection.execute(text("SELECT current_database()")).scalar_one() != "fides_test":
                pytest.fail("Connected database must be fides_test before running migrations.")
        # Schema readiness must not depend on the migration test running first.
        backend = Path(__file__).resolve().parents[2] / "backend"
        cfg = Config(str(backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend / "migrations"))
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("DATABASE_URL", settings.test_database_url)
            command.upgrade(cfg, "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def alembic_config(db_engine, monkeypatch) -> Config:
    """Migration operations use only the already validated test database."""
    backend = Path(__file__).resolve().parents[2] / "backend"
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    monkeypatch.setenv("DATABASE_URL", db_engine.url.render_as_string(hide_password=False))
    return cfg


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
