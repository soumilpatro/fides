"""B10-D0 closed due-date request and participant-only response."""

from uuid import UUID

from pydantic import Field, StrictStr, field_validator

from app.api.auth_schemas import AuthSchema, UtcDatetime
from app.api.connection_schemas import ParticipantResponse
from app.api.term_schemas import DateOnly
from app.models.enums import ExtensionStatus


class ExtensionRequestBody(AuthSchema):
    requested_due_date: DateOnly
    reason: StrictStr | None = Field(
        default=None,
        description="Trim whitespace; blank becomes null; maximum 500 characters after trimming.",
    )

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value):
        if value is None:
            return None
        value = value.strip()
        if len(value) > 500:
            raise ValueError("Reason exceeds maximum length")
        return value or None


class ExtensionResponse(AuthSchema):
    id: UUID
    commitment_id: UUID
    requested_by: ParticipantResponse
    status: ExtensionStatus
    base_terms_version_id: UUID
    previous_due_date: DateOnly
    requested_due_date: DateOnly
    reason: StrictStr | None
    decided_by: ParticipantResponse | None
    decided_at: UtcDatetime | None
    created_at: UtcDatetime
