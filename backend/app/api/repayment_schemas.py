"""Closed B7-D0 report and participant-only response shapes."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr, field_validator

from app.api.auth_schemas import AuthSchema, UtcDatetime
from app.api.connection_schemas import ParticipantResponse
from app.api.term_schemas import DateOnly
from app.models.enums import RepaymentStatus


class RepaymentRequest(AuthSchema):
    amount_minor: Annotated[StrictInt, Field(gt=0)]
    currency: Literal["INR", "USD", "GBP"]
    payment_date: DateOnly
    note: StrictStr | None = Field(
        default=None, description="Trim whitespace; blank becomes null; maximum 500 characters."
    )

    @field_validator("note")
    @classmethod
    def note_value(cls, value):
        if value is None:
            return None
        value = value.strip()
        if len(value) > 500:
            raise ValueError("Note exceeds maximum length")
        return value or None


class RepaymentResponse(AuthSchema):
    id: UUID
    commitment_id: UUID
    reported_by: ParticipantResponse
    amount_minor: StrictInt
    currency: Literal["INR", "USD", "GBP"]
    payment_date: DateOnly
    reported_at: UtcDatetime
    status: RepaymentStatus
    note: StrictStr | None
    created_at: UtcDatetime
