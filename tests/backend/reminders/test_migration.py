from uuid import uuid4

import pytest
from alembic import command
from app.db.base import Base
from app.models.notification_event import NotificationEvent
from app.models.notification_preference import NotificationPreference
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_migration_metadata(db_engine):
    inspector = inspect(db_engine)
    assert (
        inspector.get_pk_constraint("notification_preferences")["name"]
        == "pk_notification_preferences"
    )
    fk = inspector.get_foreign_keys("notification_preferences")[0]
    assert fk["name"] == "fk_notification_preferences_user_id_users"
    assert fk["options"]["ondelete"] == "RESTRICT"
    assert "uq_notification_events_dedupe_key" in {
        row["name"] for row in inspector.get_unique_constraints("notification_events")
    }
    expected = {
        constraint.name for constraint in Base.metadata.tables["notification_events"].constraints
    }
    assert "ck_notification_events_reminder_dedupe" in expected
    assert "ck_notification_events_reminder_dedupe" in {
        row["name"] for row in inspector.get_check_constraints("notification_events")
    }
    assert "ix_notification_events_created_at_id" in {
        row["name"] for row in inspector.get_indexes("notification_events")
    }


@pytest.mark.parametrize("kind", ["UPCOMING_DUE", "DUE_TODAY", "OVERDUE"])
def test_reminder_key_required(env, kind):
    with pytest.raises(IntegrityError), env.api.factory.begin() as db:
        db.add(
            NotificationEvent(
                user_id=env.users["A"],
                type=kind,
                status="DELIVERED",
                payload={},
                created_at=env.api.clock.now,
            )
        )


def test_null_workflow_keys_allowed(env):
    with env.api.factory.begin() as db:
        for _ in range(2):
            db.add(
                NotificationEvent(
                    user_id=env.users["A"],
                    type="COMMITMENT_PROPOSED",
                    status="DELIVERED",
                    payload={},
                    created_at=env.api.clock.now,
                )
            )


def test_downgrade_refuses_data_loss(env, alembic_config):
    env.preference()
    with pytest.raises(RuntimeError, match="Archive preference/reminder data"):
        command.downgrade(alembic_config, "012")
    with env.api.factory() as db:
        assert db.get(NotificationPreference, env.users["A"]) is not None


def test_upgrade_preserves_workflow_and_rejects_legacy_reminders(db_engine, alembic_config):
    identifier, user = uuid4(), uuid4()
    command.downgrade(alembic_config, "012")
    try:
        with db_engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO users (id, display_name, timezone) "
                    "VALUES (:id, 'Migration', 'UTC')"
                ),
                {"id": user},
            )
            db.execute(
                text(
                    "INSERT INTO notification_events (id,user_id,type,status,payload) "
                    "VALUES (:id,:user,'COMMITMENT_PROPOSED','DELIVERED','{}')"
                ),
                {"id": identifier, "user": user},
            )
            before = db.execute(
                text("SELECT to_jsonb(n) FROM notification_events n WHERE id=:id"),
                {"id": identifier},
            ).scalar_one()
            db.execute(
                text("UPDATE notification_events SET type='UPCOMING_DUE' WHERE id=:id"),
                {"id": identifier},
            )
        with pytest.raises(RuntimeError, match="Pre-existing reminder rows"):
            command.upgrade(alembic_config, "013")
        with db_engine.begin() as db:
            assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "012"
            db.execute(
                text("UPDATE notification_events SET type='COMMITMENT_PROPOSED' WHERE id=:id"),
                {"id": identifier},
            )
        command.upgrade(alembic_config, "013")
        with db_engine.connect() as db:
            after = db.execute(
                text("SELECT to_jsonb(n) FROM notification_events n WHERE id=:id"),
                {"id": identifier},
            ).scalar_one()
            assert after.pop("dedupe_key") is None
            assert after == before
    finally:
        with db_engine.begin() as db:
            db.execute(text("DELETE FROM notification_events WHERE id=:id"), {"id": identifier})
            db.execute(text("DELETE FROM users WHERE id=:id"), {"id": user})
        command.upgrade(alembic_config, "head")
