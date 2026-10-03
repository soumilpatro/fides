"""Approved closed mutual-closure inputs and participant-only projections."""

from typing import Annotated
from uuid import UUID

from pydantic import Field, StrictStr, field_validator

from app.api.auth_schemas import AuthSchema, UtcDatetime
from app.api.connection_schemas import ParticipantResponse
from app.api.ledger_schemas import Currency
from app.models.enums import MutualClosureStatus


class ClosureRequestCreate(AuthSchema):
    note: StrictStr | None = Field(
        default=None,
        description="Trim whitespace; blank becomes null; maximum 500 characters after trimming.",
    )

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value):
        if value is None:
            return None
        value = value.strip()
        if len(value) > 500:
            raise ValueError("Note exceeds maximum length")
        return value or None


class ClosureResponse(AuthSchema):
    id: UUID
    commitment_id: UUID
    requested_by: ParticipantResponse
    counterparty: ParticipantResponse
    status: MutualClosureStatus
    currency: Currency
    outstanding_snapshot_minor: Annotated[int, Field(strict=True, gt=0)]
    waived_amount_minor: Annotated[int, Field(strict=True, gt=0)]
    note: StrictStr | None
    decided_by: ParticipantResponse | None
    decided_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
