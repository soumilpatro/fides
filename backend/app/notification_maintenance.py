"""Bounded retention, independent of reminders and all financial writers."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.models.notification_event import NotificationEvent


def cleanup_notifications(sessions, *, now=None, batch_size=1000, max_batches=100):
    if not 1 <= batch_size <= 1000 or not 1 <= max_batches <= 100:
        raise ValueError("Invalid cleanup bounds")
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Cleanup clock must be timezone aware")
    count = 0
    for _ in range(max_batches):
        with sessions.begin() as db:
            ids = list(
                db.scalars(
                    select(NotificationEvent.id)
                    .where(NotificationEvent.created_at < now - timedelta(days=90))
                    .order_by(NotificationEvent.created_at, NotificationEvent.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            if ids:
                db.execute(delete(NotificationEvent).where(NotificationEvent.id.in_(ids)))
        count += len(ids)
        if len(ids) < batch_size:
            break
    return count
