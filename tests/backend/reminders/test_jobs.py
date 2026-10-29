import pytest
from app.jobs import notification_cleanup, reminders


@pytest.fixture(autouse=True)
def preserve_test_logging(monkeypatch):
    # CLI processes own root logging; in-process unit tests must keep pytest's
    # capture handlers intact. Real startup is validated by the command smoke test.
    for module in (reminders, notification_cleanup):
        monkeypatch.setattr(module, "configure_logging", lambda *args: None)


@pytest.mark.parametrize("failures,expected", [(0, 0), (1, 1)])
def test_reminder_job_exit(monkeypatch, failures, expected):
    monkeypatch.setattr(reminders, "get_sessionmaker", lambda: object())
    monkeypatch.setattr(
        reminders.ReminderService, "run", lambda _: {"created": 0, "failed_candidates": failures}
    )
    assert reminders.main() == expected


@pytest.mark.parametrize("module", [reminders, notification_cleanup])
def test_job_startup_error_safe(monkeypatch, caplog, module):
    def fail():
        raise RuntimeError("secret-credential")

    monkeypatch.setattr(module, "get_sessionmaker", fail)
    assert module.main() == 1
    assert "secret-credential" not in caplog.text


def test_cleanup_job_exit(monkeypatch):
    monkeypatch.setattr(notification_cleanup, "get_sessionmaker", lambda: object())
    monkeypatch.setattr(notification_cleanup, "cleanup_notifications", lambda _: 3)
    assert notification_cleanup.main() == 0


@pytest.mark.parametrize("phase", ["configuration", "session_factory", "reminder_pass"])
def test_failure_diagnostics_are_useful_and_private(monkeypatch, caplog, phase):
    import json

    from app.core.logging import _JsonFormatter
    from psycopg.errors import InsufficientPrivilege
    from sqlalchemy.exc import ProgrammingError

    private = "postgresql://name:secret@host/db +919876543210 token-value financial-999"

    def fail(*args):
        raise ProgrammingError(
            "SELECT " + private, {"payload": private}, InsufficientPrivilege(private)
        )

    monkeypatch.setattr(reminders, "get_sessionmaker", lambda: object())
    monkeypatch.setattr(
        reminders.ReminderService, "run", lambda _: {"created": 0, "failed_candidates": 0}
    )
    if phase == "configuration":
        monkeypatch.setattr(reminders, "get_settings", fail)
    elif phase == "session_factory":
        monkeypatch.setattr(reminders, "get_sessionmaker", fail)
    else:
        monkeypatch.setattr(reminders.ReminderService, "run", fail)
    assert reminders.main() == 1
    record = next(r for r in caplog.records if r.message == "reminder_job_failed")
    output = _JsonFormatter().format(record)
    fields = json.loads(output)
    assert fields["exception_category"] == "permission_denied"
    assert fields["sqlstate"] == "42501"
    assert fields["failure_phase"] == phase
    assert fields["application_traceback"][-1]["file"] == "jobs/reminders.py"
    assert fields["application_traceback"][-1]["function"] == "main"
    assert fields["application_traceback"][-1]["line"] > 0
    assert record.exc_info is None
    for sensitive in [private, "secret", "+919876543210", "token-value", "financial-999", "SELECT"]:
        assert sensitive not in output


def test_unknown_exception_and_sqlstate_are_not_reflected():
    from sqlalchemy.exc import ProgrammingError

    class PrivateExceptionName(Exception):
        sqlstate = "private-state"

    error = ProgrammingError(
        "secret-query", {"phone": "private-phone"}, PrivateExceptionName("secret")
    )
    fields = reminders.failure_fields(error, "reminder_pass")
    assert fields == {
        "exception_category": "database_error",
        "failure_phase": "reminder_pass",
        "application_traceback": [],
    }
