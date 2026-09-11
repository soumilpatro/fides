"""Isolated 011 -> 012 -> 011 validation with representative B1 data."""

from uuid import uuid4

from alembic import command
from app.models import AuditLog, AuthIdentity, Commitment, Connection, LedgerEvent, User
from app.models.enums import CommitmentStatus, CommitmentType, ConnectionStatus
from sqlalchemy import inspect, text


def snapshot(connection, tables):
    # Names come only from PostgreSQL inspection, never request input.
    quote = connection.dialect.identifier_preparer.quote
    return {
        name: connection.execute(
            text(
                "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id), '[]'::jsonb) "
                f"FROM {quote(name)} t"
            )
        ).scalar_one()
        for name in tables
    }


def test_migration_012_preserves_b1_data_and_downgrades(db_engine, alembic_config):
    auth_tables = {"auth_sessions", "auth_otp_challenges", "auth_rate_limit_buckets"}
    user_a, user_b, connection_id, commitment_id, audit_id, ledger_id, identity_id = (
        uuid4() for _ in range(7)
    )
    try:
        command.downgrade(alembic_config, "011")
        with db_engine.begin() as connection:
            tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
            assert not tables & auth_tables
            connection.execute(
                User.__table__.insert(),
                [
                    {"id": user_a, "display_name": "Migration lender", "timezone": "UTC"},
                    {"id": user_b, "display_name": "Migration borrower", "timezone": "UTC"},
                ],
            )
            connection.execute(
                AuthIdentity.__table__.insert().values(
                    id=identity_id,
                    user_id=user_a,
                    provider="migration-test",
                    provider_subject=str(user_a),
                )
            )
            connection.execute(
                Connection.__table__.insert().values(
                    id=connection_id,
                    requester_user_id=user_a,
                    recipient_user_id=user_b,
                    status=ConnectionStatus.ACCEPTED,
                )
            )
            connection.execute(
                Commitment.__table__.insert().values(
                    id=commitment_id,
                    connection_id=connection_id,
                    lender_user_id=user_a,
                    borrower_user_id=user_b,
                    type=CommitmentType.IOU,
                    status=CommitmentStatus.DRAFT,
                    principal_amount_minor=10000,
                    currency="INR",
                    created_by_user_id=user_a,
                )
            )
            connection.execute(
                AuditLog.__table__.insert().values(
                    id=audit_id,
                    actor_user_id=user_a,
                    action="MIGRATION_TEST",
                    object_type="commitment",
                    object_id=commitment_id,
                    result="SUCCESS",
                )
            )
            connection.execute(
                LedgerEvent.__table__.insert().values(
                    id=ledger_id,
                    commitment_id=commitment_id,
                    event_type="MIGRATION_TEST",
                    actor_user_id=user_a,
                    amount_minor=10000,
                    currency="INR",
                    occurred_at=text("now()"),
                )
            )
            before = snapshot(connection, tables)

        command.upgrade(alembic_config, "012")
        with db_engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == tables | auth_tables | {
                "alembic_version"
            }
            assert snapshot(connection, tables) == before
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                == "012"
            )

        command.downgrade(alembic_config, "011")
        with db_engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == tables | {"alembic_version"}
            assert snapshot(connection, tables) == before
    finally:
        # Restore head and remove only this test's seed rows even on assertion failure.
        command.upgrade(alembic_config, "head")
        with db_engine.begin() as connection:
            for model, ids in (
                (LedgerEvent, [ledger_id]),
                (AuditLog, [audit_id]),
                (Commitment, [commitment_id]),
                (Connection, [connection_id]),
                (AuthIdentity, [identity_id]),
                (User, [user_a, user_b]),
            ):
                connection.execute(model.__table__.delete().where(model.id.in_(ids)))
