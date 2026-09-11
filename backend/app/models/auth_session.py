"""Hashed session persistence only; B2-D2 section 9."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("octet_length(access_token_hash) = 32", name="access_hash_length"),
        CheckConstraint("octet_length(refresh_token_hash) = 32", name="refresh_hash_length"),
        UniqueConstraint("access_token_hash"),
        UniqueConstraint("refresh_token_hash"),
        CheckConstraint("created_at < access_expires_at", name="access_after_creation"),
        CheckConstraint("access_expires_at <= refresh_expires_at", name="access_before_refresh"),
        CheckConstraint("rotation_count >= 0", name="rotation_non_negative"),
        CheckConstraint(
            "(rotation_count = 0 AND last_rotated_at IS NULL) OR "
            "(rotation_count > 0 AND last_rotated_at IS NOT NULL "
            "AND last_rotated_at >= created_at)",
            name="rotation_timestamp",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="revocation_pair",
        ),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation_time"),
        CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN ('LOGOUT', 'ACCOUNT_DEACTIVATED')",
            name="revocation_reason",
        ),
        Index("ix_auth_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_auth_sessions_refresh_expires_at", "refresh_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    access_token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    access_expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    refresh_expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    last_rotated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    rotation_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
