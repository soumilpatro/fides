"""001 extensions and enums

Revision ID: 001
Revises:
Create Date: 2026-09-06

Creates the pgcrypto extension (used for gen_random_uuid() primary keys
across every table) and all 10 native PostgreSQL enum types defined in
Database & Data Model Specification v1.0, Sec. 4.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENUMS: dict[str, list[str]] = {
    "user_status": ["ACTIVE", "DEACTIVATED", "ANONYMIZED"],
    "connection_status": ["PENDING", "ACCEPTED", "BLOCKED", "REMOVED"],
    "commitment_type": ["IOU", "PEER_LOAN"],
    "commitment_status": [
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
    ],
    "interest_type": ["NONE", "SIMPLE_FIXED"],
    "repayment_status": ["PENDING_VERIFICATION", "VERIFIED", "DISPUTED", "CANCELLED"],
    "verification_decision": ["VERIFIED", "DISPUTED"],
    "extension_status": ["REQUESTED", "ACCEPTED", "REJECTED", "CANCELLED"],
    "installment_status": ["PENDING", "PARTIALLY_PAID", "PAID", "OVERDUE", "CANCELLED"],
    "notification_status": ["PENDING", "SENT", "DELIVERED", "FAILED", "READ"],
}


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    bind = op.get_bind()
    for name, values in _ENUMS.items():
        PGEnum(*values, name=name, create_type=True).create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name, values in reversed(list(_ENUMS.items())):
        PGEnum(*values, name=name, create_type=True).drop(bind, checkfirst=True)

    # Symmetric with upgrade(): this migration created pgcrypto, so its
    # downgrade removes it, satisfying B1's "downgrade leaves the database
    # exactly as it was before" gate. Safe here because migration 001 is
    # always the last migration removed in a full downgrade-to-base chain,
    # i.e. nothing from later FIDES migrations still depends on it by the
    # time this runs.
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
