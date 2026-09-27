"""Closed B11 inbox projections, independent of delivery providers."""

from typing import Literal
from uuid import UUID

from app.api.auth_schemas import AuthSchema, UtcDatetime
from app.api.connection_schemas import ParticipantResponse

NotificationType = Literal[
    "COMMITMENT_PROPOSED",
    "COMMITMENT_CONFIRMED",
    "COMMITMENT_REJECTED",
    "COMMITMENT_CANCELLED",
    "REPAYMENT_REPORTED",
    "REPAYMENT_VERIFIED",
    "REPAYMENT_DISPUTED",
    "EXTENSION_REQUESTED",
    "EXTENSION_ACCEPTED",
    "EXTENSION_REJECTED",
]


class NotificationResponse(AuthSchema):
    id: UUID
    type: NotificationType
    actor: ParticipantResponse
    commitment_id: UUID
    repayment_id: UUID | None
    extension_request_id: UUID | None
    created_at: UtcDatetime
    read_at: UtcDatetime | None


class NotificationListResponse(AuthSchema):
    items: list[NotificationResponse]
    next_cursor: str | None
