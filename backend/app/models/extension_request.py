"""`extension_requests` table model (Database Spec Sec. 4 - extension_requests).

Sequenced in migration 010 per the approved B1 migration order (this
table is defined in the Database Spec's Sec. 4 but was absent from its
own Sec. 13 migration file list — the approved plan resolves that gap by
giving it an explicit migration number, 010).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ExtensionStatus, extension_status_enum


class ExtensionRequest(Base):
    __tablename__ = "extension_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitments.id"), nullable=False
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    requested_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_terms: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ExtensionStatus] = mapped_column(extension_status_enum, nullable=False)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
