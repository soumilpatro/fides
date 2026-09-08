"""005 terms and installments

Revision ID: 005
Revises: 004
Create Date: 2026-09-06

Note: monotonic increase of version_no per commitment is an
application-enforced guarantee (B6+), not a plain SQL constraint here,
per the approved B1 decision.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BIGINT, ENUM as PGEnum, JSONB, UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

interest_type_enum = PGEnum("NONE", "SIMPLE_FIXED", name="interest_type", create_type=False)
installment_status_enum = PGEnum(
    "PENDING", "PARTIALLY_PAID", "PAID", "OVERDUE", "CANCELLED",
    name="installment_status", create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "commitment_terms_versions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "commitment_id", UUID(as_uuid=True), sa.ForeignKey("commitments.id"), nullable=False
        ),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("effective_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("interest_type", interest_type_enum, nullable=False),
        sa.Column("interest_rate_bps", sa.Integer, nullable=True),
        sa.Column("grace_period_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("schedule_definition", JSONB, nullable=True),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "commitment_id", "version_no", name="uq_commitment_terms_versions_commitment_version"
        ),
        sa.CheckConstraint(
            "interest_rate_bps IS NULL OR interest_rate_bps >= 0",
            name="ck_commitment_terms_versions_interest_rate_bps_non_negative",
        ),
        sa.CheckConstraint(
            "grace_period_days >= 0",
            name="ck_commitment_terms_versions_grace_period_non_negative",
        ),
    )

    op.create_table(
        "commitment_installments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "commitment_id", UUID(as_uuid=True), sa.ForeignKey("commitments.id"), nullable=False
        ),
        sa.Column(
            "terms_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("commitment_terms_versions.id"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("principal_amount_minor", BIGINT, nullable=False),
        sa.Column("interest_amount_minor", BIGINT, nullable=False),
        sa.Column("total_due_minor", BIGINT, nullable=False),
        sa.Column("status", installment_status_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "commitment_id", "sequence_no", name="uq_commitment_installments_commitment_sequence"
        ),
        sa.CheckConstraint(
            "principal_amount_minor >= 0",
            name="ck_commitment_installments_principal_non_negative",
        ),
        sa.CheckConstraint(
            "interest_amount_minor >= 0",
            name="ck_commitment_installments_interest_non_negative",
        ),
        sa.CheckConstraint(
            "total_due_minor > 0", name="ck_commitment_installments_total_due_positive"
        ),
    )
    op.create_index(
        "ix_commitment_installments_commitment_due_date",
        "commitment_installments",
        ["commitment_id", "due_date"],
    )
    op.create_index(
        "ix_commitment_installments_status_due_date",
        "commitment_installments",
        ["status", "due_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_commitment_installments_status_due_date", table_name="commitment_installments"
    )
    op.drop_index(
        "ix_commitment_installments_commitment_due_date", table_name="commitment_installments"
    )
    op.drop_table("commitment_installments")
    op.drop_table("commitment_terms_versions")
