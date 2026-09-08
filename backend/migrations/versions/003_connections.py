"""003 connections

Revision ID: 003
Revises: 002
Create Date: 2026-09-06

Note: the UNIQUE constraint on (requester_user_id, recipient_user_id)
prevents an exact duplicate in the same direction only. True canonical
(order-independent) pair de-duplication is deferred to the application
service layer (B4+), per the approved B1 decision not to introduce
triggers for this class of invariant.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

connection_status_enum = PGEnum(
    "PENDING", "ACCEPTED", "BLOCKED", "REMOVED", name="connection_status", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "requester_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "recipient_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("status", connection_status_enum, nullable=False),
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
            "requester_user_id <> recipient_user_id", name="ck_connections_distinct_users"
        ),
        sa.UniqueConstraint(
            "requester_user_id", "recipient_user_id", name="uq_connections_requester_recipient"
        ),
    )
    op.create_index(
        "ix_connections_requester_status", "connections", ["requester_user_id", "status"]
    )
    op.create_index(
        "ix_connections_recipient_status", "connections", ["recipient_user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_connections_recipient_status", table_name="connections")
    op.drop_index("ix_connections_requester_status", table_name="connections")
    op.drop_table("connections")
