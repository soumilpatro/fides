"""010 extension requests

Revision ID: 010
Revises: 009
Create Date: 2026-09-06

extension_requests is defined in Database Spec Sec. 4 but was absent
from that document's own Sec. 13 migration file list. The approved B1
migration sequence resolves this gap by giving it an explicit slot here
(010), before the final indexes/permissions migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PGEnum, JSONB, UUID

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

extension_status_enum = PGEnum(
    "REQUESTED", "ACCEPTED", "REJECTED", "CANCELLED",
    name="extension_status", create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "extension_requests",
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
            "requested_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("requested_due_date", sa.Date, nullable=True),
        sa.Column("requested_terms", JSONB, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("status", extension_status_enum, nullable=False),
        sa.Column(
            "decided_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("extension_requests")
