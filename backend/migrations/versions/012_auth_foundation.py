"""012 authentication foundation (B2-D2).

Revision ID: 012
Revises: 011

Only additive auth-state tables. Historical/financial schema is unchanged.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("access_token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("access_expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_rotated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rotation_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN ('LOGOUT', 'ACCOUNT_DEACTIVATED')",
            name=op.f("ck_auth_sessions_revocation_reason"),
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name=op.f("ck_auth_sessions_revocation_pair"),
        ),
        sa.CheckConstraint(
            "(rotation_count = 0 AND last_rotated_at IS NULL) OR "
            "(rotation_count > 0 AND last_rotated_at IS NOT NULL "
            "AND last_rotated_at >= created_at)",
            name=op.f("ck_auth_sessions_rotation_timestamp"),
        ),
        sa.CheckConstraint(
            "access_expires_at <= refresh_expires_at",
            name=op.f("ck_auth_sessions_access_before_refresh"),
        ),
        sa.CheckConstraint(
            "created_at < access_expires_at", name=op.f("ck_auth_sessions_access_after_creation")
        ),
        sa.CheckConstraint(
            "octet_length(access_token_hash) = 32", name=op.f("ck_auth_sessions_access_hash_length")
        ),
        sa.CheckConstraint(
            "octet_length(refresh_token_hash) = 32",
            name=op.f("ck_auth_sessions_refresh_hash_length"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_auth_sessions_revocation_time"),
        ),
        sa.CheckConstraint(
            "rotation_count >= 0", name=op.f("ck_auth_sessions_rotation_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("access_token_hash", name=op.f("uq_auth_sessions_access_token_hash")),
        sa.UniqueConstraint("refresh_token_hash", name=op.f("uq_auth_sessions_refresh_token_hash")),
    )
    op.create_index(
        "ix_auth_sessions_refresh_expires_at", "auth_sessions", ["refresh_expires_at"], unique=False
    )
    op.create_index(
        "ix_auth_sessions_user_revoked", "auth_sessions", ["user_id", "revoked_at"], unique=False
    )
    op.create_table(
        "auth_otp_challenges",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("intent", sa.String(length=6), nullable=False),
        sa.Column("provider_key", sa.String(length=30), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="SENDING", nullable=False),
        sa.Column("verify_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_requested_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("operation_id", sa.UUID(), nullable=True),
        sa.Column("operation_expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("consumed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(state = 'CONSUMED' AND consumed_at IS NOT NULL) OR "
            "(state <> 'CONSUMED' AND consumed_at IS NULL)",
            name=op.f("ck_auth_otp_challenges_consumed_state"),
        ),
        sa.CheckConstraint(
            "(state IN ('SENDING', 'CHECKING') AND operation_id IS NOT NULL "
            "AND operation_expires_at IS NOT NULL) OR "
            "(state NOT IN ('SENDING', 'CHECKING') AND operation_id IS NULL "
            "AND operation_expires_at IS NULL)",
            name=op.f("ck_auth_otp_challenges_operation_state"),
        ),
        sa.CheckConstraint(
            "intent IN ('signup', 'login')", name=op.f("ck_auth_otp_challenges_intent")
        ),
        sa.CheckConstraint(
            "state IN ('SENDING', 'PENDING', 'CHECKING', 'CONSUMED', 'EXPIRED', "
            "'LOCKED', 'FAILED', 'INDETERMINATE')",
            name=op.f("ck_auth_otp_challenges_state"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('PENDING', 'CHECKING', 'CONSUMED') OR provider_reference IS NOT NULL",
            name=op.f("ck_auth_otp_challenges_provider_reference_required"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_auth_otp_challenges_expiry_after_creation")
        ),
        sa.CheckConstraint(
            "verify_attempts >= 0", name=op.f("ck_auth_otp_challenges_attempts_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_otp_challenges")),
    )
    op.create_index(
        "ix_auth_otp_challenges_expires_at", "auth_otp_challenges", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_auth_otp_challenges_phone_created",
        "auth_otp_challenges",
        ["phone_e164", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "uq_auth_otp_challenges_live_phone_intent",
        "auth_otp_challenges",
        ["phone_e164", "intent"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('SENDING', 'PENDING', 'CHECKING', 'LOCKED', 'INDETERMINATE')"
        ),
    )
    op.create_index(
        "uq_auth_otp_challenges_provider_reference",
        "auth_otp_challenges",
        ["provider_key", "provider_reference"],
        unique=True,
        postgresql_where=sa.text("provider_reference IS NOT NULL"),
    )
    op.create_table(
        "auth_rate_limit_buckets",
        sa.Column("policy", sa.String(length=40), nullable=False),
        sa.Column("subject_hash", sa.LargeBinary(), nullable=False),
        sa.Column("window_started_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > window_started_at",
            name=op.f("ck_auth_rate_limit_buckets_expiry_after_window_start"),
        ),
        sa.CheckConstraint(
            "octet_length(subject_hash) = 32",
            name=op.f("ck_auth_rate_limit_buckets_subject_hash_length"),
        ),
        sa.CheckConstraint(
            "request_count >= 0", name=op.f("ck_auth_rate_limit_buckets_count_non_negative")
        ),
        sa.PrimaryKeyConstraint(
            "policy", "subject_hash", "window_started_at", name=op.f("pk_auth_rate_limit_buckets")
        ),
    )
    op.create_index(
        "ix_auth_rate_limit_buckets_expires_at",
        "auth_rate_limit_buckets",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limit_buckets_expires_at", table_name="auth_rate_limit_buckets")
    op.drop_table("auth_rate_limit_buckets")
    op.drop_index(
        "uq_auth_otp_challenges_provider_reference",
        table_name="auth_otp_challenges",
        postgresql_where=sa.text("provider_reference IS NOT NULL"),
    )
    op.drop_index(
        "uq_auth_otp_challenges_live_phone_intent",
        table_name="auth_otp_challenges",
        postgresql_where=sa.text(
            "state IN ('SENDING', 'PENDING', 'CHECKING', 'LOCKED', 'INDETERMINATE')"
        ),
    )
    op.drop_index("ix_auth_otp_challenges_phone_created", table_name="auth_otp_challenges")
    op.drop_index("ix_auth_otp_challenges_expires_at", table_name="auth_otp_challenges")
    op.drop_table("auth_otp_challenges")
    op.drop_index("ix_auth_sessions_user_revoked", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_refresh_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
