"""B13 closed diagnostics around existing transactions; never retry an operation."""

import logging
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AuthError, FinancialError
from app.core.logging import get_request_id, sanitize_request_id

logger = logging.getLogger("fides.reliability")
STATES = {
    "40P01": "deadlock",
    "40001": "serialization_failure",
    "55P03": "lock_timeout",
    "57014": "statement_timeout",
    "23502": "integrity_error",
    "23503": "integrity_error",
    "23505": "integrity_error",
    "23514": "integrity_error",
    "08000": "connection_failure",
    "08003": "connection_failure",
    "08006": "connection_failure",
    "08007": "connection_failure",
    "08P01": "connection_failure",
    "57P01": "connection_failure",
    "57P02": "connection_failure",
    "57P03": "connection_failure",
}
OPERATIONS = {"commitments", "repayments", "verification", "extensions", "summary"}


def log_failure(error, operation, phase, request_id=None):
    state = getattr(getattr(error, "orig", None), "sqlstate", None)
    category = STATES.get(state, "database_error")
    outcome = "unknown"
    if isinstance(error, FinancialError):
        category = (
            "idempotency_conflict" if error.code == "IDEMPOTENCY_CONFLICT" else "state_conflict"
        )
        outcome = "rolled_back"
    elif category not in {"connection_failure", "database_error"}:
        outcome = "rolled_back"
    elif phase == "commit":
        # Once COMMIT is attempted, a lost connection/ack cannot prove rollback.
        outcome = "uncertain"
    fields = {
        "event": "commit_uncertain" if outcome == "uncertain" else "reliability_failure",
        "operation_category": operation if operation in OPERATIONS else "unknown",
        "failure_phase": phase if phase in {"body", "commit"} else "unknown",
        "safe_database_category": category,
        "request_id": sanitize_request_id(request_id or get_request_id()),
        "commit_outcome": outcome,
    }
    if state in STATES:
        fields["sqlstate"] = state
    logger.warning("Reliability operation failed", extra={"fields": fields})


@contextmanager
def transaction(factory, operation):
    """Retain sessionmaker.begin semantics and distinguish body from commit failure.

    The exception is observed after the original context manager's cleanup. Its
    original type/public mapping is preserved. No SQL or exception text is logged.
    """
    phase = "body"
    try:
        with factory.begin() as db:
            yield db
            phase = "commit"
    except (SQLAlchemyError, FinancialError, AuthError) as error:
        diagnostic = error
        if isinstance(error, AuthError):
            # B3 already maps SQL failures to a safe AuthError. Observe its
            # retained exception context without changing B3/public behavior.
            diagnostic = error.__context__
            if error.code != "SERVICE_UNAVAILABLE" or not isinstance(diagnostic, SQLAlchemyError):
                raise
        if not isinstance(error, FinancialError) or error.code in {
            "CONFLICT",
            "IDEMPOTENCY_CONFLICT",
            "INVALID_STATE",
            "ALREADY_VERIFIED",
        }:
            log_failure(diagnostic, operation, phase)
        raise
