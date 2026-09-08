"""006 repayments and verification

Revision ID: 006
Revises: 005
Create Date: 2026-09-06

Note on idempotency_key_id: the Database Spec defines this column as a
FK to idempotency_keys.id, but the approved B1 migration sequence
creates repayments here (006) before idempotency_keys exists (008). The
column is created here as a plain nullable UUID with NO foreign key
constraint; the FK constraint itself is added in migration 008 via
ALTER TABLE, once idempotency_keys exists. This keeps the approved
migration order unchanged while still producing the exact schema from
the Database Spec once all migrations have run. Flagged during
implementation rather than silently resolved by reordering migrations.

Note on currency: "repayment currency must equal commitment currency"
is a cross-table invariant deferred to the application/service layer
(B7+), per the approved B1 decision not to introduce triggers.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BIGINT, ENUM as PGEnum, UUID

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

repayment_status_enum = PGEnum(
    "PENDING_VERIFICATION", "VERIFIED", "DISPUTED", "CANCELLED",
    name="repayment_status", create_type=False,
)
verification_decision_enum = PGEnum(
    "VERIFIED", "DISPUTED", name="verification_decision", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "repayments",
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
            "reported_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("amount_minor", BIGINT, nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("payment_date", sa.Date, nullable=False),
        sa.Column("reported_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", repayment_status_enum, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        # No FK yet — see module docstring. FK added in migration 008.
        sa.Column("idempotency_key_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_repayments_amount_positive"),
    )
    op.create_index(
        "ix_repayments_commitment_reported_at", "repayments", ["commitment_id", "reported_at"]
    )
    op.create_index("ix_repayments_commitment_status", "repayments", ["commitment_id", "status"])
    op.create_index(
        "ix_repayments_reporter_reported_at", "repayments", ["reported_by_user_id", "reported_at"]
    )

    op.create_table(
        "repayment_verifications",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "repayment_id", UUID(as_uuid=True), sa.ForeignKey("repayments.id"), nullable=False
        ),
        sa.Column(
            "decided_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("decision", verification_decision_enum, nullable=False),
        sa.Column("decision_note", sa.Text, nullable=True),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_repayment_verifications_repayment_decided_at",
        "repayment_verifications",
        ["repayment_id", "decided_at"],
    )
    op.create_index(
        "ix_repayment_verifications_verifier_decided_at",
        "repayment_verifications",
        ["decided_by_user_id", "decided_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_repayment_verifications_verifier_decided_at", table_name="repayment_verifications"
    )
    op.drop_index(
        "ix_repayment_verifications_repayment_decided_at", table_name="repayment_verifications"
    )
    op.drop_table("repayment_verifications")

    op.drop_index("ix_repayments_reporter_reported_at", table_name="repayments")
    op.drop_index("ix_repayments_commitment_status", table_name="repayments")
    op.drop_index("ix_repayments_commitment_reported_at", table_name="repayments")
    op.drop_table("repayments")
