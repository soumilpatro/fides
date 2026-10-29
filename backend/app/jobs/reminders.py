"""Run once with python -m app.jobs.reminders."""

import logging
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.reminders import ReminderService

# Closed SQLSTATE vocabulary: never copy exception messages, SQL or bind values.
_DATABASE_FAILURES = {
    "42501": "permission_denied",
    "42P01": "missing_table",
    "42703": "missing_column",
    "42704": "missing_object",
    "28P01": "database_authentication",
    "3D000": "missing_database",
    "08001": "connection_failure",
    "08006": "connection_failure",
    "57P01": "connection_failure",
    "23505": "integrity_error",
    "23503": "integrity_error",
    "23514": "integrity_error",
    "22P02": "invalid_database_value",
    "40001": "serialization_failure",
    "40P01": "deadlock",
    "57014": "statement_timeout",
}
_APP_ROOT = Path(__file__).resolve().parents[1]


def failure_fields(error, phase):
    """Bounded application stack locations, without source lines or local values."""
    category = "unexpected_error"
    if isinstance(error, ValidationError):
        category = "configuration_validation"
    elif isinstance(error, SQLAlchemyError):
        category = "database_error"
    elif isinstance(error, ValueError | TypeError):
        category = "invalid_value"
    state = getattr(getattr(error, "orig", None), "sqlstate", None)
    fields = {"failure_phase": phase, "exception_category": category}
    if state in _DATABASE_FAILURES:
        fields.update(sqlstate=state, exception_category=_DATABASE_FAILURES[state])
    frames = []
    tb = error.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        try:
            source = Path(code.co_filename).resolve().relative_to(_APP_ROOT)
        except ValueError:
            pass
        else:
            frames.append(
                {"file": source.as_posix(), "function": code.co_name, "line": tb.tb_lineno}
            )
        tb = tb.tb_next
    fields["application_traceback"] = frames[-16:]
    return fields


def main():
    configure_logging()  # Also structure failures that occur while loading settings.
    phase = "configuration"
    try:
        configure_logging(get_settings().log_level)
        phase = "session_factory"
        sessions = get_sessionmaker()
        phase = "reminder_pass"
        result = ReminderService(sessions).run()
        logging.getLogger(__name__).info("reminder_job_complete", extra={"fields": result})
        return 1 if result["failed_candidates"] else 0
    except Exception as error:
        logging.getLogger(__name__).error(
            "reminder_job_failed", extra={"fields": failure_fields(error, phase)}
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
