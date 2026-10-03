"""013 additive reminder dedupe, retention index, and preference persistence.

Downgrade refuses populated preferences/reminders: operators must explicitly
archive and remove those records first. No silent data loss or row rewriting.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

REMINDERS = "type IN ('UPCOMING_DUE', 'DUE_TODAY', 'OVERDUE')"


def upgrade():
    if (
        op.get_bind()
        .execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM notification_events WHERE {REMINDERS})"))
        .scalar_one()
    ):
        raise RuntimeError("Pre-existing reminder rows require review before migration 013")
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("due_reminders_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "overdue_reminders_enabled", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
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
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_preferences")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_notification_preferences_user_id_users"),
        ),
    )
    op.add_column("notification_events", sa.Column("dedupe_key", sa.String(160), nullable=True))
    op.create_unique_constraint(
        "uq_notification_events_dedupe_key", "notification_events", ["dedupe_key"]
    )
    op.create_check_constraint(
        op.f("ck_notification_events_reminder_dedupe"),
        "notification_events",
        f"NOT ({REMINDERS}) OR dedupe_key IS NOT NULL",
    )
    op.create_index(
        "ix_notification_events_created_at_id", "notification_events", ["created_at", "id"]
    )


def downgrade():
    db = op.get_bind()
    if (
        db.execute(sa.text("SELECT EXISTS (SELECT 1 FROM notification_preferences)")).scalar_one()
        or db.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM notification_events WHERE "
                f"{REMINDERS} OR dedupe_key IS NOT NULL)"
            )
        ).scalar_one()
    ):
        raise RuntimeError("Archive preference/reminder data before downgrading migration 013")
    op.drop_index("ix_notification_events_created_at_id", table_name="notification_events")
    op.drop_constraint(
        op.f("ck_notification_events_reminder_dedupe"), "notification_events", type_="check"
    )
    op.drop_constraint("uq_notification_events_dedupe_key", "notification_events", type_="unique")
    op.drop_column("notification_events", "dedupe_key")
    op.drop_table("notification_preferences")
