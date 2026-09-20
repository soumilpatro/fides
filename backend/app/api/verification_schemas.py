"""B8-D0 closed decision input and public history projection."""

from uuid import UUID

from pydantic import Field, StrictStr, field_validator

from app.api.auth_schemas import AuthSchema, UtcDatetime
from app.api.connection_schemas import ParticipantResponse
from app.models.enums import VerificationDecision


class DecisionRequest(AuthSchema):
    decision_note: StrictStr | None = Field(
        default=None,
        description=("Trim whitespace; blank becomes null; maximum 500 characters after trimming."),
    )

    @field_validator("decision_note")
    @classmethod
    def normalize_note(cls, value):
        if value is None:
            return None
        value = value.strip()
        if len(value) > 500:
            raise ValueError("Decision note exceeds maximum length")
        return value or None


class VerificationResponse(AuthSchema):
    id: UUID
    repayment_id: UUID
    decided_by: ParticipantResponse
    decision: VerificationDecision
    decision_note: StrictStr | None
    decided_at: UtcDatetime
