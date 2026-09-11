"""OTP operation reservations without OTP/profile persistence (B2-D2)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthOtpChallenge(Base):
    __tablename__ = "auth_otp_challenges"
    __table_args__ = (
        CheckConstraint("intent IN ('signup', 'login')", name="intent"),
        CheckConstraint(
            "state IN ('SENDING', 'PENDING', 'CHECKING', 'CONSUMED', 'EXPIRED', "
            "'LOCKED', 'FAILED', 'INDETERMINATE')",
            name="state",
        ),
        CheckConstraint("verify_attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint(
            "(state IN ('SENDING', 'CHECKING') AND operation_id IS NOT NULL "
            "AND operation_expires_at IS NOT NULL) OR "
            "(state NOT IN ('SENDING', 'CHECKING') AND operation_id IS NULL "
            "AND operation_expires_at IS NULL)",
            name="operation_state",
        ),
        CheckConstraint(
            "state NOT IN ('PENDING', 'CHECKING', 'CONSUMED') OR provider_reference IS NOT NULL",
            name="provider_reference_required",
        ),
        CheckConstraint(
            "(state = 'CONSUMED' AND consumed_at IS NOT NULL) OR "
            "(state <> 'CONSUMED' AND consumed_at IS NULL)",
            name="consumed_state",
        ),
        Index(
            "uq_auth_otp_challenges_live_phone_intent",
            "phone_e164",
            "intent",
            unique=True,
            postgresql_where=text(
                "state IN ('SENDING', 'PENDING', 'CHECKING', 'LOCKED', 'INDETERMINATE')"
            ),
        ),
        Index(
            "uq_auth_otp_challenges_provider_reference",
            "provider_key",
            "provider_reference",
            unique=True,
            postgresql_where=text("provider_reference IS NOT NULL"),
        ),
        Index("ix_auth_otp_challenges_phone_created", "phone_e164", text("created_at DESC")),
        Index("ix_auth_otp_challenges_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    intent: Mapped[str] = mapped_column(String(6), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="SENDING")
    verify_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_requested_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    operation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    operation_expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
