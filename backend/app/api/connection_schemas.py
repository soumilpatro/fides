"""Closed B4-D0 connection wire contract."""

from uuid import UUID

from pydantic import Field, StrictStr

from app.api.auth_schemas import AuthSchema, Phone, UtcDatetime
from app.models.enums import ConnectionStatus


class ConnectionRequest(AuthSchema):
    phone: Phone = Field(repr=False)


class ParticipantResponse(AuthSchema):
    id: UUID
    display_name: StrictStr


class ConnectionResponse(AuthSchema):
    id: UUID
    status: ConnectionStatus
    requester: ParticipantResponse
    recipient: ParticipantResponse
    created_at: UtcDatetime
    updated_at: UtcDatetime
