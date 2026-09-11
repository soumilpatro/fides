"""Keep library diagnostics within authentication I/O free of binds and bodies."""

import logging
import threading
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AuthError

Clock = Callable[[], datetime]
_sensitive_io = ContextVar("auth_sensitive_io", default=False)
_install_lock = threading.Lock()
_installed = False
logger = logging.getLogger("fides.auth")


def auth_operation(function):
    """Log only a closed public failure category, never arguments/SQL exceptions."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with sensitive_io():
            try:
                return function(*args, **kwargs)
            except AuthError as error:
                logger.info("Authentication operation rejected: %s", error.code)
                raise

    return wrapped


def _install_record_guard() -> None:
    global _installed
    with _install_lock:
        if _installed:
            return
        previous = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = previous(*args, **kwargs)
            if _sensitive_io.get() and record.name.startswith(("sqlalchemy.", "httpx", "httpcore")):
                record.msg = "Authentication I/O diagnostic redacted"
                record.args = ()
                record.exc_info = None
                record.exc_text = None
                record.stack_info = None
            return record

        logging.setLogRecordFactory(factory)
        _installed = True


@contextmanager
def sensitive_io():
    """Context-local across threads/tasks; redact before any handler sees a record."""
    _install_record_guard()
    token = _sensitive_io.set(True)
    try:
        yield
    finally:
        _sensitive_io.reset(token)


def utc_now(clock: Clock | None = None, db: Session | None = None) -> datetime:
    # Fresh PostgreSQL wall time after lock acquisition, not transaction-start now().
    value = (
        clock()
        if clock
        else (db.scalar(select(func.clock_timestamp())) if db is not None else datetime.now(UTC))
    )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Authentication clock must be timezone-aware")
    return value.astimezone(UTC)
