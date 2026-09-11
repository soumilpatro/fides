"""Shared rate-limit storage only; enforcement is a later B2 batch."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthRateLimitBucket(Base):
    __tablename__ = "auth_rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("octet_length(subject_hash) = 32", name="subject_hash_length"),
        CheckConstraint("request_count >= 0", name="count_non_negative"),
        CheckConstraint("expires_at > window_started_at", name="expiry_after_window_start"),
        Index("ix_auth_rate_limit_buckets_expires_at", "expires_at"),
    )

    policy: Mapped[str] = mapped_column(String(40), primary_key=True)
    subject_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
