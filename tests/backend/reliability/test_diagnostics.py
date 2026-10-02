import json
import logging

import pytest
from app.core.logging import _JsonFormatter
from sqlalchemy.exc import OperationalError


@pytest.mark.parametrize(
    "state, category",
    [
        ("40P01", "deadlock"),
        ("40001", "serialization_failure"),
        ("55P03", "lock_timeout"),
        ("57014", "statement_timeout"),
        ("23505", "integrity_error"),
        ("08006", "connection_failure"),
        ("57P01", "connection_failure"),
        ("XXXXX", "database_error"),
    ],
)
@pytest.mark.parametrize("phase", ["body", "commit"])
def test_closed_diagnostic_fields(state, category, phase, caplog):
    from app.core.reliability import log_failure

    class DriverError(Exception):
        sqlstate = state

    error = OperationalError("secret SQL", {"token": "private-token"}, DriverError("private"))
    with caplog.at_level(logging.WARNING, logger="fides.reliability"):
        log_failure(error, "repayments", phase, "safe-request-id")
    record = next(r for r in caplog.records if r.name == "fides.reliability")
    payload = json.loads(_JsonFormatter().format(record))
    assert payload["safe_database_category"] == category
    assert payload["failure_phase"] == phase
    assert payload["request_id"] == "safe-request-id"
    assert payload.get("sqlstate") == (state if state != "XXXXX" else None)
    assert payload["commit_outcome"] == (
        "uncertain"
        if phase == "commit" and category in ("connection_failure", "database_error")
        else "rolled_back"
        if category not in ("connection_failure", "database_error")
        else "unknown"
    )
    assert not record.exc_info
    assert not {"secret", "private", "token"} & set(payload)
    assert "private" not in json.dumps(payload)


def test_untrusted_request_id_and_category_are_not_logged(caplog):
    from app.core.reliability import log_failure

    with caplog.at_level(logging.WARNING, logger="fides.reliability"):
        log_failure(ValueError("private note"), "private operation", "private phase", "phone +123")
    record = next(r for r in caplog.records if r.name == "fides.reliability")
    assert "private" not in _JsonFormatter().format(record)
    assert "phone" not in _JsonFormatter().format(record)
