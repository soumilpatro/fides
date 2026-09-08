"""008 idempotency

Revision ID: 008
Revises: 007
Create Date: 2026-09-06

Creates idempotency_keys, then adds the FOREIGN KEY constraint on
repayments.idempotency_key_id (the column itself was created without a
FK in migration 006, since idempotency_keys did not exist yet at that
point in the approved migration order). See migration 006's docstring
for the full explanation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.CHAR(64), nullable=False),
        sa.Column("response_status", sa.Integer, nullable=True),
        sa.Column("response_body", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "endpoint", "idempotency_key", name="uq_idempotency_keys_user_endpoint_key"
        ),
    )

    op.create_foreign_key(
        "fk_repayments_idempotency_key_id_idempotency_keys",
        "repayments",
        "idempotency_keys",
        ["idempotency_key_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_repayments_idempotency_key_id_idempotency_keys",
        "repayments",
        type_="foreignkey",
    )
    op.drop_table("idempotency_keys")
