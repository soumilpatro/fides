"""Closed B11 inbox projections, independent of delivery providers."""

from typing import Literal
from uuid import UUID

from pydantic import model_validator

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
    "UPCOMING_DUE",
    "DUE_TODAY",
    "OVERDUE",
]


class NotificationResponse(AuthSchema):
    id: UUID
    type: NotificationType
    actor: ParticipantResponse | None
    commitment_id: UUID
    repayment_id: UUID | None
    extension_request_id: UUID | None
    created_at: UtcDatetime
    read_at: UtcDatetime | None

    @model_validator(mode="after")
    def actor_contract(self):
        reminder = self.type in ("UPCOMING_DUE", "DUE_TODAY", "OVERDUE")
        if reminder != (self.actor is None):
            raise ValueError("Actor must match notification type")
        if reminder and (self.repayment_id is not None or self.extension_request_id is not None):
            raise ValueError("Unexpected reminder resource")
        return self


class NotificationListResponse(AuthSchema):
    items: list[NotificationResponse]
    next_cursor: str | None
