"""`connections` table model (Database Spec Sec. 4 - connections).

Deferred to the application/service layer (B4+), per approved B1 decision
not to introduce triggers for cross-table/order-independent invariants:
- Preventing a duplicate *order-independent* relationship pair (i.e.
  treating A->B and B->A as the same pair). The plain UNIQUE constraint
  below only prevents an exact duplicate in the same direction; true
  canonical-pair de-duplication requires either a trigger or a computed
  canonical-order column, neither of which is introduced in B1.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ConnectionStatus, connection_status_enum


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint(
            "requester_user_id <> recipient_user_id", name="ck_connections_distinct_users"
        ),
        UniqueConstraint("requester_user_id", "recipient_user_id"),
        Index("ix_connections_requester_status", "requester_user_id", "status"),
        Index("ix_connections_recipient_status", "recipient_user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    requester_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[ConnectionStatus] = mapped_column(connection_status_enum, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
