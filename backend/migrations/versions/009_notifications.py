"""009 notifications

Revision ID: 009
Revises: 008
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PGEnum, JSONB, UUID

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

notification_status_enum = PGEnum(
    "PENDING", "SENT", "DELIVERED", "FAILED", "READ",
    name="notification_status", create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "notification_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("status", notification_status_enum, nullable=False),
        sa.Column("object_type", sa.String(50), nullable=True),
        sa.Column("object_id", UUID(as_uuid=True), nullable=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_notification_events_user_status_created_at",
        "notification_events",
        ["user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_notification_events_scheduled_at_status",
        "notification_events",
        ["scheduled_at", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_events_scheduled_at_status", table_name="notification_events"
    )
    op.drop_index(
        "ix_notification_events_user_status_created_at", table_name="notification_events"
    )
    op.drop_table("notification_events")
