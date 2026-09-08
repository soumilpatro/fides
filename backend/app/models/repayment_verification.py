"""`repayment_verifications` table model (Database Spec Sec. 4)."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import VerificationDecision, verification_decision_enum


class RepaymentVerification(Base):
    __tablename__ = "repayment_verifications"
    __table_args__ = (
        Index("ix_repayment_verifications_repayment_decided_at", "repayment_id", "decided_at"),
        Index("ix_repayment_verifications_verifier_decided_at", "decided_by_user_id", "decided_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    repayment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayments.id"), nullable=False
    )
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision: Mapped[VerificationDecision] = mapped_column(
        verification_decision_enum, nullable=False
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
