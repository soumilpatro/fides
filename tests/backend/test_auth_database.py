"""Real PostgreSQL constraint and ORM/migration agreement checks for B2-A."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.models import AuthOtpChallenge, AuthRateLimitBucket, AuthSession, Base, User
from sqlalchemy import CheckConstraint, MetaData, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema

NOW = datetime(2026, 9, 10, tzinfo=UTC)
AUTH_TABLES = {"auth_sessions", "auth_otp_challenges", "auth_rate_limit_buckets"}
APPROVED_COLUMNS = {
    "auth_sessions": {
        "id",
        "user_id",
        "access_token_hash",
        "refresh_token_hash",
        "access_expires_at",
        "refresh_expires_at",
        "created_at",
        "last_rotated_at",
        "rotation_count",
        "revoked_at",
        "revocation_reason",
    },
    "auth_otp_challenges": {
        "id",
        "phone_e164",
        "intent",
        "provider_key",
        "provider_reference",
        "state",
        "verify_attempts",
        "created_at",
        "expires_at",
        "last_requested_at",
        "operation_id",
        "operation_expires_at",
        "consumed_at",
    },
    "auth_rate_limit_buckets": {
        "policy",
        "subject_hash",
        "window_started_at",
        "request_count",
        "expires_at",
    },
}


@pytest.fixture
def user_id(db_session):
    user = User(display_name="Foundation test", timezone="UTC")
    db_session.add(user)
    db_session.flush()
    return user.id


def session_values(owner_id, **changes):
    return {
        "user_id": owner_id,
        "access_token_hash": uuid4().bytes * 2,
        "refresh_token_hash": uuid4().bytes * 2,
        "created_at": NOW,
        "access_expires_at": NOW + timedelta(minutes=15),
        "refresh_expires_at": NOW + timedelta(days=30),
        **changes,
    }


def challenge_values(**changes):
    return {
        "phone_e164": "+919876543210",
        "intent": "signup",
        "provider_key": "twilio_verify_v2_signup",
        "provider_reference": str(uuid4()),
        "state": "PENDING",
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        "last_requested_at": NOW,
        **changes,
    }


def bucket_values(**changes):
    return {
        "policy": "otp_request_phone_10m",
        "subject_hash": b"h" * 32,
        "window_started_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        **changes,
    }


def insert(db_session, model, values):
    db_session.execute(model.__table__.insert().values(**values))


def rejects(db_session, model, values):
    with pytest.raises(IntegrityError), db_session.begin_nested():
        insert(db_session, model, values)


def rejects_insert_and_update(db_session, model, valid_values, changes):
    """Exercise SQL enforcement in both write paths, including SQL NULL."""
    rejects(db_session, model, {**valid_values, **changes})
    table = model.__table__
    if "id" in table.c:
        valid_values = {**valid_values, "id": uuid4()}
    insert(db_session, model, valid_values)
    predicate = [column == valid_values[column.name] for column in table.primary_key]
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(table.update().where(*predicate).values(**changes))


def test_auth_critical_metadata_matches_migration(db_engine):
    with db_engine.connect() as connection:
        inspector = inspect(connection)
        assert AUTH_TABLES <= set(inspector.get_table_names())
        for name in AUTH_TABLES:
            table = Base.metadata.tables[name]
            columns = inspector.get_columns(name)
            assert set(table.columns.keys()) == APPROVED_COLUMNS[name]
            assert {column["name"] for column in columns} == set(table.columns.keys())
            for column in columns:
                mapped = table.c[column["name"]]
                assert column["nullable"] == mapped.nullable
                assert column["type"].compile(connection.dialect) == mapped.type.compile(
                    connection.dialect
                )
            assert inspector.get_pk_constraint(name)["constrained_columns"] == [
                column.name for column in table.primary_key
            ]
            assert {check["name"] for check in inspector.get_check_constraints(name)} == {
                check.name for check in table.constraints if isinstance(check, CheckConstraint)
            }
            expected_indexes = {index.name for index in table.indexes}
            actual_indexes = {
                index["name"]
                for index in inspector.get_indexes(name)
                if not index.get("duplicates_constraint")
            }
            assert actual_indexes == expected_indexes

        def include_object(obj, name, type_, reflected, compare_to):
            if type_ == "table":
                return name in AUTH_TABLES
            return getattr(getattr(obj, "table", None), "name", None) in AUTH_TABLES

        context = MigrationContext.configure(
            connection,
            opts={
                "include_object": include_object,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        assert compare_metadata(context, Base.metadata) == []
        foreign_keys = inspector.get_foreign_keys("auth_sessions")
        assert len(foreign_keys) == 1
        assert foreign_keys[0]["referred_table"] == "users"
        assert foreign_keys[0]["options"]["ondelete"] == "RESTRICT"
        assert not {"display_name", "timezone", "otp_code", "code"} & {
            column["name"] for column in inspector.get_columns("auth_otp_challenges")
        }


def test_postgresql_check_expressions_and_indexes_match_orm(db_engine):
    # Alembic comparison does not compare CHECK expressions or partial-index
    # predicates. Ask PostgreSQL to normalize ORM DDL in an isolated, rolled-back
    # schema so comparisons include those semantics, column order and DESC.
    with db_engine.connect() as connection, connection.begin():
        schema = "b2_review_" + uuid4().hex
        connection.execute(CreateSchema(schema))
        metadata = MetaData()
        for model in (User, AuthSession, AuthOtpChallenge, AuthRateLimitBucket):
            model.__table__.to_metadata(metadata, schema=schema)
        metadata.create_all(connection)
        inspector = inspect(connection)
        for name in AUTH_TABLES:
            assert inspector.get_check_constraints(name, schema="public") == (
                inspector.get_check_constraints(name, schema=schema)
            )
            assert inspector.get_indexes(name, schema="public") == (
                inspector.get_indexes(name, schema=schema)
            )
            assert inspector.get_unique_constraints(name, schema="public") == (
                inspector.get_unique_constraints(name, schema=schema)
            )
        assert inspector.get_pk_constraint("auth_rate_limit_buckets")["constrained_columns"] == [
            "policy",
            "subject_hash",
            "window_started_at",
        ]
        # Roll back all comparison DDL. No schema/table is retained after this test.
        connection.rollback()


def test_independent_sessions_and_defaults(db_session, user_id):
    first = session_values(user_id)
    insert(db_session, AuthSession, first)
    insert(db_session, AuthSession, session_values(user_id))
    rows = db_session.scalars(select(AuthSession).where(AuthSession.user_id == user_id)).all()
    assert len(rows) == 2
    assert all(row.id and row.rotation_count == 0 and row.revoked_at is None for row in rows)
    rejects(
        db_session,
        AuthSession,
        session_values(user_id, access_token_hash=first["access_token_hash"]),
    )
    rejects(
        db_session,
        AuthSession,
        session_values(user_id, refresh_token_hash=first["refresh_token_hash"]),
    )
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(User.__table__.delete().where(User.id == user_id))


@pytest.mark.parametrize(
    "changes",
    [
        {"access_token_hash": b"x" * 31},
        {"access_token_hash": b"x" * 33},
        {"refresh_token_hash": b"x" * 31},
        {"refresh_token_hash": b"x" * 33},
        {"access_expires_at": NOW},
        {"access_expires_at": NOW - timedelta(seconds=1)},
        {"access_expires_at": NOW + timedelta(days=31)},
        {"rotation_count": -1},
        {"rotation_count": 1},
        {"last_rotated_at": NOW},
        {"rotation_count": 1, "last_rotated_at": NOW - timedelta(seconds=1)},
        {"revoked_at": NOW},
        {"revocation_reason": "LOGOUT"},
        {"revoked_at": NOW - timedelta(seconds=1), "revocation_reason": "LOGOUT"},
        {"revoked_at": NOW, "revocation_reason": "UNKNOWN"},
        {"user_id": uuid4()},
        {"access_token_hash": None},
        {"refresh_token_hash": None},
        {"access_expires_at": None},
        {"refresh_expires_at": None},
        {"created_at": None},
        {"rotation_count": None},
    ],
)
def test_session_constraints(db_session, user_id, changes):
    rejects_insert_and_update(db_session, AuthSession, session_values(user_id), changes)


@pytest.mark.parametrize("reason", ["LOGOUT", "ACCOUNT_DEACTIVATED"])
def test_session_valid_rotation_revocation_and_expiry_boundary(db_session, user_id, reason):
    insert(
        db_session,
        AuthSession,
        session_values(
            user_id,
            rotation_count=1,
            last_rotated_at=NOW,
            revoked_at=NOW,
            revocation_reason=reason,
            access_expires_at=NOW + timedelta(days=30),
        ),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"intent": "other"},
        {"state": "OTHER"},
        {"verify_attempts": -1},
        {"expires_at": NOW},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"operation_id": uuid4()},
        {"operation_expires_at": NOW},
        {"operation_id": uuid4(), "operation_expires_at": NOW},
        {"state": "SENDING"},
        {"state": "CHECKING"},
        {"state": "SENDING", "operation_id": uuid4()},
        {"state": "SENDING", "operation_expires_at": NOW},
        {"provider_reference": None},
        {
            "state": "CHECKING",
            "operation_id": uuid4(),
            "operation_expires_at": NOW,
            "provider_reference": None,
        },
        {"state": "CONSUMED"},
        {"consumed_at": NOW},
        {"state": "CONSUMED", "consumed_at": NOW, "provider_reference": None},
        {"intent": None},
        {"state": None},
        {"verify_attempts": None},
        {"created_at": None},
        {"expires_at": None},
    ],
)
def test_challenge_constraints(db_session, changes):
    rejects_insert_and_update(db_session, AuthOtpChallenge, challenge_values(), changes)


@pytest.mark.parametrize("intent", ["signup", "login"])
@pytest.mark.parametrize("state", ["SENDING", "PENDING", "CHECKING", "LOCKED", "INDETERMINATE"])
def test_live_uniqueness_per_intent_and_opposite_intent_coexistence(db_session, intent, state):
    values = challenge_values(intent=intent, state=state)
    if state in {"SENDING", "CHECKING"}:
        values.update(operation_id=uuid4(), operation_expires_at=NOW + timedelta(seconds=30))
    insert(db_session, AuthOtpChallenge, values)
    rejects(db_session, AuthOtpChallenge, {**values, "provider_reference": str(uuid4())})
    opposite = "login" if intent == "signup" else "signup"
    insert(
        db_session,
        AuthOtpChallenge,
        challenge_values(intent=opposite, provider_key=f"twilio_verify_v2_{opposite}"),
    )


@pytest.mark.parametrize("state", ["EXPIRED", "FAILED", "CONSUMED"])
def test_terminal_challenge_does_not_reserve_phone_intent(db_session, state):
    changes = {"state": state}
    if state == "CONSUMED":
        changes["consumed_at"] = NOW
    insert(db_session, AuthOtpChallenge, challenge_values(**changes))
    insert(db_session, AuthOtpChallenge, challenge_values())


def test_provider_reference_uniqueness_and_nullable_sending_reference(db_session):
    values = challenge_values(state="FAILED", provider_reference="opaque-reference")
    insert(db_session, AuthOtpChallenge, values)
    rejects(db_session, AuthOtpChallenge, {**values, "phone_e164": "+442083661177"})
    insert(db_session, AuthOtpChallenge, {**values, "provider_key": "twilio_verify_v2_login"})
    # Multiple NULL references within one provider must remain permitted.
    insert(db_session, AuthOtpChallenge, {**values, "provider_reference": None})
    insert(db_session, AuthOtpChallenge, {**values, "provider_reference": None})
    insert(
        db_session,
        AuthOtpChallenge,
        challenge_values(
            state="SENDING",
            provider_reference=None,
            operation_id=uuid4(),
            operation_expires_at=NOW + timedelta(seconds=30),
        ),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"subject_hash": b"x" * 31},
        {"subject_hash": b"x" * 33},
        {"request_count": -1},
        {"expires_at": NOW},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"subject_hash": None},
        {"request_count": None},
        {"expires_at": None},
        {"window_started_at": None},
    ],
)
def test_bucket_constraints(db_session, changes):
    rejects_insert_and_update(db_session, AuthRateLimitBucket, bucket_values(), changes)


def test_bucket_composite_primary_key(db_session):
    values = bucket_values()
    insert(db_session, AuthRateLimitBucket, values)
    rejects(db_session, AuthRateLimitBucket, values)
    insert(db_session, AuthRateLimitBucket, bucket_values(policy="otp_request_ip_10m"))
    insert(db_session, AuthRateLimitBucket, bucket_values(subject_hash=b"i" * 32))
    insert(
        db_session,
        AuthRateLimitBucket,
        bucket_values(
            window_started_at=NOW + timedelta(minutes=10), expires_at=NOW + timedelta(minutes=20)
        ),
    )
    rows = db_session.scalars(select(AuthRateLimitBucket)).all()
    assert len(rows) == 4
    assert all(row.request_count == 0 for row in rows)


def test_migrations_refuse_database_override_before_ddl(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import conftest

    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = "fides_dev"
    upgrade = MagicMock()
    monkeypatch.setattr(
        conftest,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql+psycopg://localhost/fides_dev",
            test_database_url="postgresql+psycopg://localhost/fides_test?dbname=fides_dev",
        ),
    )
    monkeypatch.setattr(conftest, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(conftest.command, "upgrade", upgrade)
    fixture = conftest.db_engine.__wrapped__()
    with pytest.raises(pytest.fail.Exception, match="Connected database must be fides_test"):
        next(fixture)
    upgrade.assert_not_called()
    engine.dispose.assert_called_once()
