"""`commitment_terms_versions` table model (Database Spec Sec. 4).

Deferred to the application/service layer (B6+): version_no monotonic
increase per commitment is an application-enforced guarantee, not a
plain SQL constraint (would require a trigger to enforce generally).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import InterestType, interest_type_enum


class CommitmentTermsVersion(Base):
    __tablename__ = "commitment_terms_versions"
    __table_args__ = (
        UniqueConstraint("commitment_id", "version_no"),
        CheckConstraint(
            "interest_rate_bps IS NULL OR interest_rate_bps >= 0",
            name="ck_commitment_terms_versions_interest_rate_bps_non_negative",
        ),
        CheckConstraint(
            "grace_period_days >= 0", name="ck_commitment_terms_versions_grace_period_non_negative"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitments.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    interest_type: Mapped[InterestType] = mapped_column(interest_type_enum, nullable=False)
    interest_rate_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grace_period_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    schedule_definition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
