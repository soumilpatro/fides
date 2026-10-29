from datetime import timedelta
from uuid import uuid4

import pytest
from app.reminders import ReminderService
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker


def test_runtime_role_conflict_target_requires_select(env):
    engine = env.api.factory.kw["bind"]
    with engine.connect() as conn, conn.begin() as outer:
        assert conn.scalar(text("SELECT current_database()")) == "fides_test"
        role = "reminder_test_" + uuid4().hex
        conn.execute(text(f"CREATE ROLE {role} NOLOGIN"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        grants = {
            "commitments": "SELECT",
            "commitment_terms_versions": "SELECT",
            "users": "SELECT (id, status)",
            "commitment_installments": (
                "SELECT (id, commitment_id, terms_version_id, due_date, sequence_no)"
            ),
            "repayments": (
                "SELECT (commitment_id, status, amount_minor, currency, reported_by_user_id)"
            ),
            "notification_preferences": (
                "SELECT (user_id, due_reminders_enabled, overdue_reminders_enabled)"
            ),
            "notification_events": "INSERT, SELECT (id)",
        }
        for table, grant in grants.items():
            conn.execute(text(f"GRANT {grant} ON {table} TO {role}"))
        factory = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")
        job = ReminderService(factory)
        conn.execute(text(f"SET LOCAL ROLE {role}"))
        assert job.run(now=env.api.clock.now + timedelta(days=1)) == {
            "created": 0,
            "failed_candidates": 0,
        }
        with pytest.raises(ProgrammingError) as failure:
            job.run(now=env.api.clock.now)
        assert failure.value.orig.sqlstate == "42501"
        conn.execute(text("RESET ROLE"))
        conn.execute(text(f"GRANT SELECT (dedupe_key) ON notification_events TO {role}"))
        conn.execute(text(f"SET LOCAL ROLE {role}"))
        assert job.run(now=env.api.clock.now) == {"created": 1, "failed_candidates": 0}
        assert job.run(now=env.api.clock.now) == {"created": 0, "failed_candidates": 0}
        assert not conn.scalar(
            text(
                "SELECT has_column_privilege(current_user, "
                "'notification_events', 'payload', 'SELECT')"
            )
        )
        assert not conn.scalar(
            text("SELECT has_table_privilege(current_user, 'notification_events', 'UPDATE')")
        )
        outer.rollback()  # role, grants and notification inserts are test-only
