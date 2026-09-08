"""011 indexes

Revision ID: 011
Revises: 010
Create Date: 2026-09-06

Adds the two indexes from Database Spec Sec. 6 not already attached
inline at table creation:
  - commitment_terms_versions(commitment_id, effective_at)
  - idempotency_keys(expires_at)

Despite the filename "indexes_permissions" inherited from the Database
Spec's own migration plan (Sec. 13), this migration is INDEXES ONLY. No
database role, grant, or permission DDL is included here, per the
approved B1 decision: least-privilege role provisioning is documented
in docs/database-roles.md and provisioned separately from ordinary
application Alembic migrations, not executed by this file.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_commitment_terms_versions_commitment_effective_at",
        "commitment_terms_versions",
        ["commitment_id", "effective_at"],
    )
    op.create_index(
        "ix_idempotency_keys_expires_at",
        "idempotency_keys",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_idempotency_keys_expires_at", table_name="idempotency_keys"
    )
    op.drop_index(
        "ix_commitment_terms_versions_commitment_effective_at",
        table_name="commitment_terms_versions",
    )
