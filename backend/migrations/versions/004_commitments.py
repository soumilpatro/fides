"""004 commitments

Revision ID: 004
Revises: 003
Create Date: 2026-09-06

Note: the invariant "connection_id must connect the same two users as
lender_user_id/borrower_user_id" cannot be expressed as a plain
CHECK/FOREIGN KEY constraint (it requires cross-table lookup) and is
deferred to the application/service layer (B5+), per the approved B1
decision not to introduce triggers for this class of invariant.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BIGINT, ENUM as PGEnum, UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

commitment_type_enum = PGEnum("IOU", "PEER_LOAN", name="commitment_type", create_type=False)
commitment_status_enum = PGEnum(
    "DRAFT",
    "PENDING_CONFIRMATION",
    "CONFIRMED",
    "ACTIVE",
    "PARTIALLY_REPAID",
    "FULLY_REPAID",
    "CLOSED",
    "REJECTED",
    "CANCELLED",
    "DISPUTED",
    "DEFAULTED",
    name="commitment_status",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "commitments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "connection_id", UUID(as_uuid=True), sa.ForeignKey("connections.id"), nullable=False
        ),
        sa.Column(
            "lender_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "borrower_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("type", commitment_type_enum, nullable=False),
        sa.Column("status", commitment_status_enum, nullable=False),
        sa.Column("principal_amount_minor", BIGINT, nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("activated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "lender_user_id <> borrower_user_id", name="ck_commitments_distinct_parties"
        ),
        sa.CheckConstraint(
            "principal_amount_minor > 0", name="ck_commitments_principal_positive"
        ),
    )
    op.create_index("ix_commitments_lender_status", "commitments", ["lender_user_id", "status"])
    op.create_index(
        "ix_commitments_borrower_status", "commitments", ["borrower_user_id", "status"]
    )
    op.create_index(
        "ix_commitments_connection_created_at", "commitments", ["connection_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_commitments_connection_created_at", table_name="commitments")
    op.drop_index("ix_commitments_borrower_status", table_name="commitments")
    op.drop_index("ix_commitments_lender_status", table_name="commitments")
    op.drop_table("commitments")
