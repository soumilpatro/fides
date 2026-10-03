"""Dedicated, durable full-waiver proposals; migration 014 owns the enum."""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, BigInteger, CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import MutualClosureStatus, mutual_closure_status_enum


class MutualClosureRequest(Base):
    __tablename__ = "mutual_closure_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitments.id"), nullable=False
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    counterparty_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[MutualClosureStatus] = mapped_column(mutual_closure_status_enum, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    outstanding_snapshot_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    waived_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint("requested_by_user_id <> counterparty_user_id", name="distinct_parties"),
        CheckConstraint("outstanding_snapshot_minor > 0", name="positive_snapshot"),
        CheckConstraint("waived_amount_minor > 0", name="positive_waiver"),
        CheckConstraint("waived_amount_minor = outstanding_snapshot_minor", name="full_waiver"),
        CheckConstraint("currency IN ('INR','USD','GBP')", name="currency"),
        CheckConstraint("note IS NULL OR char_length(note) <= 500", name="note_length"),
        CheckConstraint(
            "(status = 'REQUESTED' AND decided_by_user_id IS NULL AND decided_at IS NULL) OR "
            "(status IN ('ACCEPTED','REJECTED') AND decided_by_user_id IS NOT NULL AND "
            "decided_by_user_id = counterparty_user_id AND decided_at IS NOT NULL) OR "
            "(status = 'CANCELLED' AND decided_by_user_id IS NOT NULL AND "
            "decided_by_user_id = requested_by_user_id AND decided_at IS NOT NULL)",
            name="decision",
        ),
        Index(
            "uq_mutual_closure_requests_requested_commitment",
            "commitment_id",
            unique=True,
            postgresql_where=text("status = 'REQUESTED'"),
        ),
        Index(
            "ix_mutual_closure_requests_commitment_created_at_id",
            "commitment_id",
            text("created_at DESC"),
            text("id ASC"),
        ),
    )
