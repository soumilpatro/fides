"""Shared pytest fixtures for FIDES backend tests (B0 scope).

Only a FastAPI TestClient fixture is needed at B0. Database fixtures,
authenticated-client fixtures, and domain factories are introduced in
later phases (B1+) once persistence and identity exist.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    """A TestClient bound to a freshly-created app instance per test."""
    app = create_app()
    return TestClient(app)
