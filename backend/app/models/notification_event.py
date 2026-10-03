"""`notification_events` table model (Database Spec Sec. 4 - notification_events)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import NotificationStatus, notification_status_enum


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_notification_events_dedupe_key"),
        CheckConstraint(
            "type NOT IN ('UPCOMING_DUE', 'DUE_TODAY', 'OVERDUE') OR dedupe_key IS NOT NULL",
            name="reminder_dedupe",
        ),
        Index("ix_notification_events_created_at_id", "created_at", "id"),
        Index("ix_notification_events_user_status_created_at", "user_id", "status", "created_at"),
        Index("ix_notification_events_scheduled_at_status", "scheduled_at", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(notification_status_enum, nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
