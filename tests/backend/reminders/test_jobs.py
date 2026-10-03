import pytest
from app.jobs import notification_cleanup, reminders


@pytest.fixture(autouse=True)
def preserve_test_logging(monkeypatch):
    # CLI processes own root logging; in-process unit tests must keep pytest's
    # capture handlers intact. Real startup is validated by the command smoke test.
    for module in (reminders, notification_cleanup):
        monkeypatch.setattr(module, "configure_logging", lambda _: None)


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
