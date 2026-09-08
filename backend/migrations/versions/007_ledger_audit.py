"""007 ledger and audit

Revision ID: 007
Revises: 006
Create Date: 2026-09-06

Append-only by convention: the application database role must not have
UPDATE/DELETE grants on these two tables. That restriction is documented
in docs/database-roles.md and provisioned separately from Alembic
migrations (approved B1 decision) — no table-level constraint enforces
it here.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BIGINT, JSONB, UUID

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ledger_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "commitment_id", UUID(as_uuid=True), sa.ForeignKey("commitments.id"), nullable=False
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column(
            "actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("amount_minor", BIGINT, nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column(
            "repayment_id", UUID(as_uuid=True), sa.ForeignKey("repayments.id"), nullable=True
        ),
        sa.Column(
            "terms_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("commitment_terms_versions.id"),
            nullable=True,
        ),
        sa.Column(
            "event_payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_ledger_events_commitment_created_at", "ledger_events", ["commitment_id", "created_at"]
    )
    op.create_index(
        "ix_ledger_events_event_type_created_at", "ledger_events", ["event_type", "created_at"]
    )

    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("object_type", sa.String(50), nullable=False),
        sa.Column("object_id", UUID(as_uuid=True), nullable=False),
        sa.Column("result", sa.String(30), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_audit_logs_object_type_object_id_created_at",
        "audit_logs",
        ["object_type", "object_id", "created_at"],
    )
    op.create_index("ix_audit_logs_actor_created_at", "audit_logs", ["actor_user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_actor_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_object_type_object_id_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_ledger_events_event_type_created_at", table_name="ledger_events")
    op.drop_index("ix_ledger_events_commitment_created_at", table_name="ledger_events")
    op.drop_table("ledger_events")
