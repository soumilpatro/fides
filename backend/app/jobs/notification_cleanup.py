"""Run once with a maintenance-authorized DATABASE_URL; scheduling belongs to B15."""

import logging

from app.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.notification_maintenance import cleanup_notifications


def main():
    try:
        configure_logging(get_settings().log_level)
        count = cleanup_notifications(get_sessionmaker())
        logging.getLogger(__name__).info(
            "notification_cleanup_complete", extra={"fields": {"deleted": count}}
        )
        return 0
    except Exception:
        logging.getLogger(__name__).error("notification_cleanup_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
