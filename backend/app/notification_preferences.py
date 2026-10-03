"""Preference transactions lock the current user/session only."""

from sqlalchemy.dialects.postgresql import insert

from app.api.notification_preference_schemas import NotificationPreferences
from app.auth.safety import auth_operation, utc_now
from app.models.notification_preference import NotificationPreference


class PreferenceService:
    def __init__(self, sessions):
        self.sessions = sessions

    @auth_operation
    def read(self, principal):
        with self.sessions.sessions.begin() as db:
            self.sessions.revalidate_user_locked(db, principal)
            row = db.get(NotificationPreference, principal.user_id)
            return NotificationPreferences(
                due_reminders_enabled=row.due_reminders_enabled if row else True,
                overdue_reminders_enabled=row.overdue_reminders_enabled if row else True,
            )

    @auth_operation
    def write(self, principal, body):
        with self.sessions.sessions.begin() as db:
            self.sessions.revalidate_user_locked(db, principal)
            now = utc_now(self.sessions.clock, db)
            values = body.model_dump()
            row = db.execute(
                insert(NotificationPreference)
                .values(user_id=principal.user_id, created_at=now, updated_at=now, **values)
                .on_conflict_do_update(
                    index_elements=[NotificationPreference.user_id],
                    set_={**values, "updated_at": now},
                )
                .returning(
                    NotificationPreference.due_reminders_enabled,
                    NotificationPreference.overdue_reminders_enabled,
                )
            ).one()
            return NotificationPreferences(**row._mapping)
