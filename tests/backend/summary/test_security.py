from uuid import UUID

import pytest
from sqlalchemy import event

from app.models.connection import Connection
from app.models.user import User
from .conftest import bucket, read


@pytest.mark.parametrize("status", ["BLOCKED", "REMOVED"])
def test_connection_state_cannot_erase_finances(b7, status):
    with b7.api.factory.begin() as db:
        db.get(Connection, UUID(b7.connection)).status = status
    assert bucket(b7)["borrowed_outstanding_minor"] == 10000
    assert bucket(b7, "B")["lent_outstanding_minor"] == 10000


def test_deactivated_counterparty(b7):
    with b7.api.factory.begin() as db:
        db.get(User, b7.users["B"]).status = "DEACTIVATED"
    assert bucket(b7)["borrowed_outstanding_minor"] == 10000


def test_connection_only_has_no_financial_access(b7):
    result = b7.call("POST", json={"phone": b7.phones["C"]})
    assert result.status_code == 201
    assert b7.call("POST", "/" + result.json()["id"] + "/accept", actor="C").status_code == 200
    assert all(
        row["borrowed_outstanding_minor"] == row["lent_outstanding_minor"] == 0
        for row in read(b7, "C").json()["currencies"]
    )


def test_no_domain_writes_and_constant_query_count(b7):
    engine = b7.api.factory.kw["bind"]
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert read(b7).status_code == 200
        first = list(statements)
        for _ in range(8):
            b7.commitment()
        statements.clear()
        assert read(b7).status_code == 200
        assert len(statements) == len(first)
        assert not any(
            s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements
        )
        locks = [s for s in statements if "FOR UPDATE" in s]
        assert locks and all("FROM users" in s for s in locks)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
