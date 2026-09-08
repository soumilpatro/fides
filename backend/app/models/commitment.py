"""`commitments` table model (Database Spec Sec. 4 - commitments).

Deferred to the application/service layer (B5+), per approved B1
decision not to introduce triggers for cross-table invariants:
- `connection_id` must connect the same two users as `lender_user_id`/
  `borrower_user_id`. This cross-table check is not expressible as a
  plain PostgreSQL CHECK/FK constraint without a trigger.
"""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import BIGINT, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import (
    CommitmentStatus,
    CommitmentType,
    commitment_status_enum,
    commitment_type_enum,
)


class Commitment(Base):
    __tablename__ = "commitments"
    __table_args__ = (
        CheckConstraint(
            "lender_user_id <> borrower_user_id", name="ck_commitments_distinct_parties"
        ),
        CheckConstraint("principal_amount_minor > 0", name="ck_commitments_principal_positive"),
        Index("ix_commitments_lender_status", "lender_user_id", "status"),
        Index("ix_commitments_borrower_status", "borrower_user_id", "status"),
        Index("ix_commitments_connection_created_at", "connection_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id"), nullable=False
    )
    lender_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    borrower_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    type: Mapped[CommitmentType] = mapped_column(commitment_type_enum, nullable=False)
    status: Mapped[CommitmentStatus] = mapped_column(commitment_status_enum, nullable=False)
    principal_amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
