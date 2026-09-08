"""`commitment_installments` table model (Database Spec Sec. 4)."""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import BIGINT, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import InstallmentStatus, installment_status_enum


class CommitmentInstallment(Base):
    __tablename__ = "commitment_installments"
    __table_args__ = (
        UniqueConstraint("commitment_id", "sequence_no"),
        CheckConstraint(
            "principal_amount_minor >= 0", name="ck_commitment_installments_principal_non_negative"
        ),
        CheckConstraint(
            "interest_amount_minor >= 0", name="ck_commitment_installments_interest_non_negative"
        ),
        CheckConstraint(
            "total_due_minor > 0", name="ck_commitment_installments_total_due_positive"
        ),
        Index("ix_commitment_installments_commitment_due_date", "commitment_id", "due_date"),
        Index("ix_commitment_installments_status_due_date", "status", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitments.id"), nullable=False
    )
    terms_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitment_terms_versions.id"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    principal_amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)
    interest_amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)
    total_due_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)
    status: Mapped[InstallmentStatus] = mapped_column(installment_status_enum, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
