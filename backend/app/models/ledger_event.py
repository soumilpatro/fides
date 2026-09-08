"""`ledger_events` table model (Database Spec Sec. 4 - ledger_events).

Append-only by convention (Database Spec Sec. 5, 14): the application
database role must not have UPDATE/DELETE grants on this table. That
role/grant restriction is documented in docs/database-roles.md and
provisioned separately from Alembic migrations (approved B1 decision),
not enforced by a table-level constraint here.
"""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import BIGINT, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LedgerEvent(Base):
    __tablename__ = "ledger_events"
    __table_args__ = (
        Index("ix_ledger_events_commitment_created_at", "commitment_id", "created_at"),
        Index("ix_ledger_events_event_type_created_at", "event_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitments.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    amount_minor: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    repayment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayments.id"), nullable=True
    )
    terms_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitment_terms_versions.id"), nullable=True
    )
    event_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
