import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from app.db.base import Base
from app.models.enums import MutualClosureStatus
from app.models.mutual_closure_request import MutualClosureRequest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from .conftest import requested


def test_enum_columns_constraints_indexes_and_fks(db_engine):
    inspector = inspect(db_engine)
    table = Base.metadata.tables["mutual_closure_requests"]
    actual = {c["name"]: c for c in inspector.get_columns(table.name)}
    assert set(actual) == set(table.c.keys())
    assert {k: c["nullable"] for k, c in actual.items()} == {c.name: c.nullable for c in table.c}
    enum = next(e for e in inspector.get_enums() if e["name"] == "mutual_closure_status")
    assert enum["labels"] == [s.value for s in MutualClosureStatus]
    assert table.c.status.type.create_type is False
    assert {c["name"] for c in inspector.get_check_constraints(table.name)} == {
        c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"
    }
    fks = inspector.get_foreign_keys(table.name)
    assert len(fks) == 4
    assert all(f["referred_columns"] == ["id"] and not f["options"].get("ondelete") for f in fks)
    assert {f["name"] for f in fks} == {f.name for f in table.foreign_key_constraints}
    indexes = {i["name"]: i for i in inspector.get_indexes(table.name)}
    assert set(indexes) == {i.name for i in table.indexes}
    unique = indexes["uq_mutual_closure_requests_requested_commitment"]
    assert unique["unique"] and unique["column_names"] == ["commitment_id"]
    assert "REQUESTED" in str(unique["dialect_options"]["postgresql_where"])
    with db_engine.connect() as db:
        history = db.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = "
                "'ix_mutual_closure_requests_commitment_created_at_id'"
            )
        ).scalar_one()
    assert "commitment_id, created_at DESC, id" in history
    assert "gen_random_uuid()" in actual["id"]["default"]
    assert all("now()" in actual[c]["default"] for c in ("created_at", "updated_at"))


@pytest.mark.parametrize(
    "damage",
    [
        "same_parties",
        "zero_snapshot",
        "negative_waiver",
        "partial_waiver",
        "currency",
        "note",
        "requested_actor",
        "requested_time",
        "accepted_no_actor",
        "accepted_no_time",
        "accepted_wrong_actor",
        "rejected_no_actor",
        "rejected_wrong_actor",
        "cancelled_no_actor",
        "cancelled_wrong_actor",
        "missing_parent",
        "missing_requester",
        "missing_counterparty",
        "missing_decider",
    ],
)
def test_database_backstops(mc, damage):
    values = dict(
        commitment_id=UUID(mc.identifier),
        requested_by_user_id=mc.users["A"],
        counterparty_user_id=mc.users["B"],
        currency="INR",
        outstanding_snapshot_minor=10000,
        waived_amount_minor=10000,
        status="REQUESTED",
        created_at=mc.api.clock.now,
        updated_at=mc.api.clock.now,
    )
    if damage == "same_parties":
        values["counterparty_user_id"] = mc.users["A"]
    elif damage == "zero_snapshot":
        values["outstanding_snapshot_minor"] = 0
    elif damage == "negative_waiver":
        values["waived_amount_minor"] = -1
    elif damage == "partial_waiver":
        values["waived_amount_minor"] = 9999
    elif damage == "currency":
        values["currency"] = "EUR"
    elif damage == "note":
        values["note"] = "x" * 501
    elif damage == "requested_actor":
        values["decided_by_user_id"] = mc.users["B"]
    elif damage == "requested_time":
        values["decided_at"] = mc.api.clock.now
    elif damage.startswith("missing_"):
        fields = {
            "missing_parent": "commitment_id",
            "missing_requester": "requested_by_user_id",
            "missing_counterparty": "counterparty_user_id",
            "missing_decider": "decided_by_user_id",
        }
        values[fields[damage]] = uuid4()
        if damage == "missing_decider":
            values.update(status="ACCEPTED", decided_at=mc.api.clock.now)
    else:
        state, _, kind = damage.partition("_")
        values.update(
            status=state.upper(),
            decided_by_user_id=mc.users["A" if state == "cancelled" else "B"],
            decided_at=mc.api.clock.now,
        )
        if kind == "no_actor":
            values["decided_by_user_id"] = None
        elif kind == "no_time":
            values["decided_at"] = None
        else:
            values["decided_by_user_id"] = mc.users["B" if state == "cancelled" else "A"]
    with pytest.raises(IntegrityError), mc.api.factory.begin() as db:
        db.add(MutualClosureRequest(**values))


def test_partial_unique_backstop_and_terminal_history(mc):
    identifier = requested(mc)
    with pytest.raises(IntegrityError), mc.api.factory.begin() as db:
        original = db.get(MutualClosureRequest, UUID(identifier))
        values = {c.name: getattr(original, c.name) for c in original.__table__.c if c.name != "id"}
        db.add(MutualClosureRequest(**values))
    assert mc.decide(identifier, "cancel", actor="A").status_code == 200
    assert requested(mc) != identifier


@pytest.mark.parametrize("kind", ["row", "ledger", "audit", "notification", "idempotency"])
def test_safe_downgrade_refuses_each_provenance(mc, kind):
    requested(mc)
    path = (
        Path(__file__).resolve().parents[3]
        / "backend/migrations/versions/014_mutual_closure_requests.py"
    )
    spec = importlib.util.spec_from_file_location("closure_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Exercise real isolated DB state; transaction rollback preserves all fixtures.
    with (
        pytest.raises(RuntimeError, match="Archive closure provenance"),
        mc.api.factory.begin() as db,
    ):
        for name, query in {
            "row": "DELETE FROM mutual_closure_requests",
            "ledger": "DELETE FROM ledger_events WHERE event_type LIKE 'MUTUAL_CLOSURE_%'",
            "audit": "DELETE FROM audit_logs WHERE object_type = 'MutualClosureRequest'",
            "notification": "DELETE FROM notification_events "
            "WHERE object_type = 'MutualClosureRequest'",
            "idempotency": "DELETE FROM idempotency_keys WHERE endpoint LIKE '%closure-requests%'",
        }.items():
            if name != kind:
                db.execute(text(query))
        with Operations.context(MigrationContext.configure(db.connection())):
            module.downgrade()


def test_upgrade_downgrade_preserves_existing_data(db_engine, alembic_config):
    script = ScriptDirectory.from_config(alembic_config)
    assert script.get_heads() == ["014"]
    assert script.get_revision("014").down_revision == "013"
    user, notice = uuid4(), uuid4()
    command.downgrade(alembic_config, "013")
    try:
        with db_engine.begin() as db:
            db.execute(
                text("INSERT INTO users (id,display_name,timezone) VALUES (:id,'Migration','UTC')"),
                {"id": user},
            )
            db.execute(
                text(
                    "INSERT INTO notification_events (id,user_id,type,status,payload) "
                    "VALUES (:id,:user,'COMMITMENT_PROPOSED','DELIVERED','{}')"
                ),
                {"id": notice, "user": user},
            )
            before = db.execute(
                text("SELECT to_jsonb(n) FROM notification_events n WHERE id=:id"), {"id": notice}
            ).scalar_one()
            assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "013"
        command.upgrade(alembic_config, "014")
        with db_engine.connect() as db:
            assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "014"
            assert (
                db.execute(
                    text("SELECT to_jsonb(n) FROM notification_events n WHERE id=:id"),
                    {"id": notice},
                ).scalar_one()
                == before
            )
        command.downgrade(alembic_config, "013")
        assert "mutual_closure_requests" not in inspect(db_engine).get_table_names()
        assert "mutual_closure_status" not in {e["name"] for e in inspect(db_engine).get_enums()}
    finally:
        with db_engine.begin() as db:
            db.execute(text("DELETE FROM notification_events WHERE id=:id"), {"id": notice})
            db.execute(text("DELETE FROM users WHERE id=:id"), {"id": user})
        command.upgrade(alembic_config, "head")
