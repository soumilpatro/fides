"""Closed B9-D0 timeline projections; storage payloads are never public schemas."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.api.auth_schemas import AuthSchema, UtcDatetime
from app.api.connection_schemas import ParticipantResponse
from app.models.enums import CommitmentStatus

Money = Annotated[int, Field(strict=True, ge=0)]
Currency = Literal["INR", "USD", "GBP"]


class ProposedDetails(AuthSchema):
    status: Literal["PENDING_CONFIRMATION"]
    terms_version_id: UUID


class ConfirmedDetails(AuthSchema):
    status: Literal["ACTIVE"]


class RejectedDetails(AuthSchema):
    status: Literal["REJECTED"]


class CancelledDetails(AuthSchema):
    status: Literal["CANCELLED"]


class ReportedDetails(AuthSchema):
    repayment_id: UUID
    terms_version_id: UUID
    amount_minor: Annotated[int, Field(strict=True, gt=0)]
    currency: Currency
    status: Literal["PENDING_VERIFICATION"]


class DisputedDetails(AuthSchema):
    repayment_id: UUID
    verification_id: UUID
    amount_minor: Annotated[int, Field(strict=True, gt=0)]
    currency: Currency
    status: Literal["DISPUTED"]


class VerifiedDetails(AuthSchema):
    repayment_id: UUID
    verification_id: UUID
    terms_version_id: UUID
    amount_minor: Annotated[int, Field(strict=True, gt=0)]
    currency: Currency
    status: Literal["VERIFIED"]
    resulting_verified_outstanding_minor: Money
    resulting_commitment_status: CommitmentStatus


class TimelineEvent(AuthSchema):
    id: UUID
    commitment_id: UUID
    actor: ParticipantResponse
    occurred_at: UtcDatetime


class ProposedEvent(TimelineEvent):
    event_type: Literal["COMMITMENT_PROPOSED"]
    details: ProposedDetails


class ConfirmedEvent(TimelineEvent):
    event_type: Literal["COMMITMENT_CONFIRMED"]
    details: ConfirmedDetails


class RejectedEvent(TimelineEvent):
    event_type: Literal["COMMITMENT_REJECTED"]
    details: RejectedDetails


class CancelledEvent(TimelineEvent):
    event_type: Literal["COMMITMENT_CANCELLED"]
    details: CancelledDetails


class ReportedEvent(TimelineEvent):
    event_type: Literal["REPAYMENT_REPORTED"]
    details: ReportedDetails


class VerifiedEvent(TimelineEvent):
    event_type: Literal["REPAYMENT_VERIFIED"]
    details: VerifiedDetails


class DisputedEvent(TimelineEvent):
    event_type: Literal["REPAYMENT_DISPUTED"]
    details: DisputedDetails


LedgerItem = Annotated[
    ProposedEvent
    | ConfirmedEvent
    | RejectedEvent
    | CancelledEvent
    | ReportedEvent
    | VerifiedEvent
    | DisputedEvent,
    Field(discriminator="event_type"),
]


class LedgerResponse(AuthSchema):
    items: list[LedgerItem]
    next_cursor: str | None
