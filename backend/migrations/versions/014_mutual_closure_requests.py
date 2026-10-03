"""014 additive mutual closure persistence; never discard closure provenance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    status = postgresql.ENUM(
        "REQUESTED",
        "ACCEPTED",
        "REJECTED",
        "CANCELLED",
        name="mutual_closure_status",
        create_type=False,
    )
    status.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "mutual_closure_requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("commitment_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=False),
        sa.Column("counterparty_user_id", sa.UUID(), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("outstanding_snapshot_minor", sa.BigInteger(), nullable=False),
        sa.Column("waived_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mutual_closure_requests")),
        *[
            sa.ForeignKeyConstraint(
                [column],
                [f"{target}.id"],
                name=op.f(f"fk_mutual_closure_requests_{column}_{target}"),
            )
            for column, target in (
                ("commitment_id", "commitments"),
                ("requested_by_user_id", "users"),
                ("counterparty_user_id", "users"),
                ("decided_by_user_id", "users"),
            )
        ],
        *[
            sa.CheckConstraint(expression, name=op.f(f"ck_mutual_closure_requests_{name}"))
            for name, expression in (
                ("distinct_parties", "requested_by_user_id <> counterparty_user_id"),
                ("positive_snapshot", "outstanding_snapshot_minor > 0"),
                ("positive_waiver", "waived_amount_minor > 0"),
                ("full_waiver", "waived_amount_minor = outstanding_snapshot_minor"),
                ("currency", "currency IN ('INR','USD','GBP')"),
                ("note_length", "note IS NULL OR char_length(note) <= 500"),
                (
                    "decision",
                    "(status = 'REQUESTED' AND decided_by_user_id IS NULL "
                    "AND decided_at IS NULL) OR "
                    "(status IN ('ACCEPTED','REJECTED') AND decided_by_user_id IS NOT NULL AND "
                    "decided_by_user_id = counterparty_user_id AND decided_at IS NOT NULL) OR "
                    "(status = 'CANCELLED' AND decided_by_user_id IS NOT NULL AND "
                    "decided_by_user_id = requested_by_user_id AND decided_at IS NOT NULL)",
                ),
            )
        ],
    )
    op.create_index(
        "uq_mutual_closure_requests_requested_commitment",
        "mutual_closure_requests",
        ["commitment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'REQUESTED'"),
    )
    op.create_index(
        "ix_mutual_closure_requests_commitment_created_at_id",
        "mutual_closure_requests",
        ["commitment_id", sa.text("created_at DESC"), sa.text("id ASC")],
    )


def downgrade():
    db = op.get_bind()
    checks = (
        "SELECT EXISTS (SELECT 1 FROM mutual_closure_requests)",
        "SELECT EXISTS (SELECT 1 FROM ledger_events WHERE event_type LIKE 'MUTUAL\\_CLOSURE\\_%')",
        "SELECT EXISTS (SELECT 1 FROM audit_logs WHERE object_type = 'MutualClosureRequest' "
        "OR action LIKE 'MUTUAL\\_CLOSURE\\_%')",
        "SELECT EXISTS (SELECT 1 FROM notification_events "
        "WHERE object_type = 'MutualClosureRequest' "
        "OR type LIKE 'MUTUAL\\_CLOSURE\\_%')",
        "SELECT EXISTS (SELECT 1 FROM idempotency_keys WHERE "
        "endpoint LIKE 'POST /api/v1/closure-requests/%' "
        "OR endpoint LIKE 'POST /api/v1/commitments/%/closure-requests')",
    )
    if any(db.execute(sa.text(query)).scalar_one() for query in checks):
        raise RuntimeError("Archive closure provenance before downgrading migration 014")
    op.drop_index(
        "ix_mutual_closure_requests_commitment_created_at_id", table_name="mutual_closure_requests"
    )
    op.drop_index(
        "uq_mutual_closure_requests_requested_commitment", table_name="mutual_closure_requests"
    )
    op.drop_table("mutual_closure_requests")
    postgresql.ENUM(name="mutual_closure_status").drop(db, checkfirst=False)
