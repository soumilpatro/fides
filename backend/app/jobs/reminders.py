"""Run once with python -m app.jobs.reminders."""

import logging

from app.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.reminders import ReminderService


def main():
    try:
        configure_logging(get_settings().log_level)
        result = ReminderService(get_sessionmaker()).run()
        logging.getLogger(__name__).info("reminder_job_complete", extra={"fields": result})
        return 1 if result["failed_candidates"] else 0
    except Exception:
        logging.getLogger(__name__).error("reminder_job_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
