"""The complete two-field preference replacement contract."""

from pydantic import StrictBool

from app.api.auth_schemas import AuthSchema


class NotificationPreferences(AuthSchema):
    due_reminders_enabled: StrictBool
    overdue_reminders_enabled: StrictBool
