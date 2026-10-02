"""Reuse migrated fides_test and existing committed HTTP fixtures only."""

import logging

import pytest

from summary.conftest import (  # noqa: F401
    api,
    b6,
    b7,
    b8,
    b10,
    clock,
    ctx,
    engine_env,
    peers,
    settings,
)


@pytest.fixture(autouse=True)
def reliability_log_capture(caplog, monkeypatch):
    # Alembic fileConfig disables preexisting loggers; app setup replaces root
    # handlers. Capture this closed logger directly without changing runtime policy.
    logger = logging.getLogger("fides.reliability")
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "propagate", False)
    logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)
