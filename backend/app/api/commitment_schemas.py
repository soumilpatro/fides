"""Approved B5-D0/D1 wire shapes with B6-D0 optional initial terms."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr, field_validator

from app.api.auth_schemas import AuthSchema, UtcDatetime
from app.api.connection_schemas import ParticipantResponse
from app.api.term_schemas import TermsRequest
from app.models.enums import CommitmentStatus


class CommitmentRequest(AuthSchema):
    # Omission is the legacy B5 path. Explicit null is not a terms object.
    terms: TermsRequest = Field(default=None)
    connection_id: UUID
    actor_role: Literal["BORROWER", "LENDER"]
    type: Literal["IOU", "PEER_LOAN"]
    principal_amount_minor: Annotated[StrictInt, Field(gt=0, le=1_000_000_000_000)]
    currency: Literal["INR", "USD", "GBP"]
    description: StrictStr | None = Field(
        default=None,
        description=(
            "Trim surrounding whitespace; blank becomes null. "
            "Maximum 500 characters after trimming."
        ),
    )

    @field_validator("description")
    @classmethod
    def description_value(cls, value):
        if value is None:
            return None
        value = value.strip()
        if len(value) > 500:
            raise ValueError("Description exceeds maximum length")
        return value or None


class CommitmentResponse(AuthSchema):
    id: UUID
    connection_id: UUID
    type: Literal["IOU", "PEER_LOAN"]
    status: CommitmentStatus
    principal_amount_minor: StrictInt
    currency: Literal["INR", "USD", "GBP"]
    description: StrictStr | None
    borrower: ParticipantResponse
    lender: ParticipantResponse
    creator: ParticipantResponse
    created_at: UtcDatetime
    updated_at: UtcDatetime
    confirmed_at: UtcDatetime | None
    activated_at: UtcDatetime | None
