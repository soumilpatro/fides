"""B1 database foundation tests.

Covers exactly the B1 gate and sub-items from the AI Development &
Backend Build Specification Sec. 8-9:
- "Migration up/down works" (the literal B1 gate).
- "Verify transaction rollback behavior" (B1 sub-item 5).
- "Add database integration-test fixture" (B1 sub-item 6 — see conftest.py).

Also verifies the schema-level constraints and structural invariants
from the Database & Data Model Specification v1.0 (Sec. 5, Sec. 11) that
are expressible in plain PostgreSQL DDL. Constraints deferred to the
future application/service layer (documented in the relevant model
modules) are intentionally NOT tested here, since there is no service
layer yet to exercise.

All tests in this file require a reachable TEST_DATABASE_URL (the
dedicated test database from docker-compose.yml). If it is not
configured, `db_engine` in conftest.py skips them.
"""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    import os

    os.environ["DATABASE_URL"] = database_url
    return cfg


def test_database_connectivity(db_engine) -> None:
    """The test engine can connect and execute a trivial query."""
    with db_engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_migration_upgrade_and_downgrade_round_trip(db_engine) -> None:
    """B1 gate: `alembic upgrade head` and `alembic downgrade base` both work.

    Runs the full chain down to base and back up to head against the
    dedicated test database, leaving it migrated to head afterward so
    subsequent tests in this file can rely on the schema existing.
    """
    # render_as_string(hide_password=False) is required here: str(url)
    # masks the password as "***" by default (a SQLAlchemy safety
    # feature for logging), which would break the real connection Alembic
    # needs to make via the DATABASE_URL environment variable.
    settings_url = db_engine.url.render_as_string(hide_password=False)
    cfg = _alembic_config(settings_url)

    # Ensure we start from a known state, then exercise both directions.
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    # Confirm downgrade actually removed everything except Alembic's own
    # bookkeeping table (alembic_version), which Alembic intentionally
    # leaves in place — it does not drop it, only empties it.
    with db_engine.connect() as conn:
        remaining_tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        }
    assert remaining_tables == {"alembic_version"}

    command.upgrade(cfg, "head")

    with db_engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        }
    expected_tables = {
        "users",
        "auth_identities",
        "connections",
        "commitments",
        "commitment_terms_versions",
        "commitment_installments",
        "repayments",
        "repayment_verifications",
        "ledger_events",
        "audit_logs",
        "idempotency_keys",
        "notification_events",
        "extension_requests",
        "alembic_version",
    }
    assert expected_tables.issubset(tables)


def test_transaction_rollback_behavior(db_engine) -> None:
    """B1 sub-item: verify transaction rollback behavior.

    Inserts a user inside a transaction, rolls it back explicitly, and
    confirms — via a separate connection — that nothing was persisted.
    """
    user_id = uuid.uuid4()
    with db_engine.connect() as conn:
        trans = conn.begin()
        conn.execute(
            text(
                "INSERT INTO users (id, display_name, timezone) "
                "VALUES (:id, 'Rollback Test User', 'UTC')"
            ),
            {"id": user_id},
        )
        trans.rollback()

    with db_engine.connect() as verify_conn:
        found = verify_conn.execute(
            text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}
        ).scalar()
    assert found == 0


def _insert_user(db_session, display_name: str = "Test User") -> uuid.UUID:
    user_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO users (id, display_name, timezone) "
            "VALUES (:id, :name, 'UTC')"
        ),
        {"id": user_id, "name": display_name},
    )
    return user_id


def _insert_connection(db_session, requester_id: uuid.UUID, recipient_id: uuid.UUID) -> uuid.UUID:
    conn_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO connections (id, requester_user_id, recipient_user_id, status) "
            "VALUES (:id, :req, :rec, 'ACCEPTED')"
        ),
        {"id": conn_id, "req": requester_id, "rec": recipient_id},
    )
    return conn_id


def test_commitment_rejects_equal_lender_and_borrower(db_session) -> None:
    """Schema-level enforcement: lender_user_id <> borrower_user_id."""
    user_id = _insert_user(db_session)
    other_id = _insert_user(db_session, "Other User")
    conn_id = _insert_connection(db_session, user_id, other_id)
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO commitments "
                "(id, connection_id, lender_user_id, borrower_user_id, type, status, "
                "principal_amount_minor, currency, created_by_user_id) "
                "VALUES (:id, :conn_id, :same_user, :same_user, 'IOU', 'DRAFT', "
                "100000, 'INR', :same_user)"
            ),
            {"id": uuid.uuid4(), "conn_id": conn_id, "same_user": user_id},
        )
    db_session.rollback()


def test_commitment_rejects_non_positive_principal(db_session) -> None:
    """Schema-level enforcement: principal_amount_minor > 0."""
    lender_id = _insert_user(db_session, "Lender")
    borrower_id = _insert_user(db_session, "Borrower")
    conn_id = _insert_connection(db_session, lender_id, borrower_id)
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO commitments "
                "(id, connection_id, lender_user_id, borrower_user_id, type, status, "
                "principal_amount_minor, currency, created_by_user_id) "
                "VALUES (:id, :conn_id, :lender, :borrower, 'IOU', 'DRAFT', "
                "0, 'INR', :lender)"
            ),
            {"id": uuid.uuid4(), "conn_id": conn_id, "lender": lender_id, "borrower": borrower_id},
        )
    db_session.rollback()


def test_idempotency_key_uniqueness_enforced(db_session) -> None:
    """Schema-level enforcement: UNIQUE(user_id, endpoint, idempotency_key)."""
    user_id = _insert_user(db_session)
    db_session.flush()

    insert_sql = text(
        "INSERT INTO idempotency_keys "
        "(id, user_id, endpoint, idempotency_key, request_hash, expires_at) "
        "VALUES (:id, :user_id, '/api/v1/commitments', 'same-key', "
        "'0000000000000000000000000000000000000000000000000000000000000000', "
        "now() + interval '1 day')"
    )
    db_session.execute(insert_sql, {"id": uuid.uuid4(), "user_id": user_id})
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(insert_sql, {"id": uuid.uuid4(), "user_id": user_id})
    db_session.rollback()


def test_multiple_independent_commitments_between_same_users(db_session) -> None:
    """Schema-level proof of Database Spec Sec. 11's worked example.

    Two commitments in the same direction plus one in the opposite
    direction between the same two users must all persist independently,
    with no unique-constraint collision.
    """
    user_a = _insert_user(db_session, "User A")
    user_b = _insert_user(db_session, "User B")
    conn_id = _insert_connection(db_session, user_a, user_b)
    db_session.flush()

    insert_commitment = text(
        "INSERT INTO commitments "
        "(id, connection_id, lender_user_id, borrower_user_id, type, status, "
        "principal_amount_minor, currency, created_by_user_id) "
        "VALUES (:id, :conn_id, :lender, :borrower, 'IOU', 'DRAFT', :amount, 'INR', :lender)"
    )

    # C1: A lends B, 10,000
    c1_id = uuid.uuid4()
    db_session.execute(
        insert_commitment,
        {"id": c1_id, "conn_id": conn_id, "lender": user_a, "borrower": user_b, "amount": 1000000},
    )
    # C2: A lends B again, 5,000 — independent commitment, same direction
    c2_id = uuid.uuid4()
    db_session.execute(
        insert_commitment,
        {"id": c2_id, "conn_id": conn_id, "lender": user_a, "borrower": user_b, "amount": 500000},
    )
    # C3: B lends A, 2,000 — opposite direction
    c3_id = uuid.uuid4()
    db_session.execute(
        insert_commitment,
        {"id": c3_id, "conn_id": conn_id, "lender": user_b, "borrower": user_a, "amount": 200000},
    )
    db_session.flush()

    count = db_session.execute(
        text("SELECT count(*) FROM commitments WHERE connection_id = :conn_id"),
        {"conn_id": conn_id},
    ).scalar()
    assert count == 3
