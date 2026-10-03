from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.models.commitment import Commitment
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.notification_event import NotificationEvent
from app.models.notification_preference import NotificationPreference
from app.reminders import REMINDER_TYPES, ReminderService
from sqlalchemy import delete, select

from notifications.conftest import (  # noqa: F401
    api,
    b6,
    b7,
    b8,
    b10,
    clock,
    ctx,
    engine_env,
    inbox,
    peers,
    settings,
)


@pytest.fixture
def env(inbox):  # noqa: F811
    parent_id = UUID(inbox.identifier)

    def configure(due="2026-09-14", grace=0, timezone="UTC", status="ACTIVE"):
        with inbox.api.factory.begin() as db:
            db.get(Commitment, parent_id).status = status
            term = db.scalar(
                select(CommitmentTermsVersion)
                .where(
                    CommitmentTermsVersion.commitment_id == parent_id,
                )
                .order_by(CommitmentTermsVersion.version_no.desc())
                .limit(1)
            )
            term.due_date = date.fromisoformat(due) if due else None
            term.grace_period_days = grace
            term.schedule_definition = {
                "schedule_mode": "single" if due else "none",
                "due_timezone": timezone,
                "installment_dates": None,
            }

    def rows():
        with inbox.api.factory() as db:
            return list(
                db.scalars(
                    select(NotificationEvent).where(
                        NotificationEvent.object_id == parent_id,
                        NotificationEvent.type.in_(REMINDER_TYPES),
                    )
                )
            )

    def preference(actor="A", due=True, overdue=True):
        return inbox.api.client.post(
            "/api/v1/notification-preferences",
            json={
                "due_reminders_enabled": due,
                "overdue_reminders_enabled": overdue,
            },
            headers=inbox.headers[actor],
        )

    configure()
    try:
        yield SimpleNamespace(
            **vars(inbox),
            parent_id=parent_id,
            configure=configure,
            rows=rows,
            preference=preference,
            job=ReminderService(inbox.api.factory),
        )
    finally:
        with inbox.api.factory.begin() as db:
            db.execute(
                delete(NotificationPreference).where(
                    NotificationPreference.user_id.in_(inbox.users.values())
                )
            )
