import pytest
from sqlalchemy import event

from .helpers import OPERATIONS, operation


@pytest.mark.parametrize("action", OPERATIONS + ("summary", "deactivate", "connection"))
def test_cross_route_canonical_lock_order(b10, action):
    if action == "summary":

        def call():
            return b10.api.client.get("/api/v1/summary", headers=b10.headers["A"])
    elif action == "deactivate":

        def call():
            return b10.api.client.post("/api/v1/me/deactivate", headers=b10.headers["C"])
    elif action == "connection":

        def call():
            return b10.call("POST", f"/{b10.connection}/block")
    else:
        call = operation(b10, action)
    engine = b10.api.factory.kw["bind"]
    locks, users = [], []

    def observe(conn, cursor, sql, parameters, context, many):
        if "pg_try_advisory_xact_lock" in sql:
            locks.append(0)
        elif "FOR UPDATE" in sql:
            for table, rank in (
                ("users", 1),
                ("connections", 2),
                ("commitments", 3),
                ("repayments", 4),
                ("extension_requests", 4),
            ):
                if f"FROM {table}" in sql:
                    if table == "users":
                        identifier = next(v for v in parameters.values() if v in b10.users.values())
                        # B3 deliberately re-locks the already held actor.
                        if identifier in users:
                            break
                        users.append(identifier)
                    if "FOR UPDATE OF commitments" in sql:
                        rank = 3
                    locks.append(rank)
                    break

    event.listen(engine, "before_cursor_execute", observe)
    try:
        result = call()
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert result.status_code in (200, 201), result.text
    assert locks and locks == sorted(locks)
    if action in OPERATIONS:
        assert locks[0] == 0
        expected = {
            "create": {0, 1, 2},
            "confirm": {0, 1, 2, 3},
            "reject": {0, 1, 3},
            "cancel": {0, 1, 3},
            "report": {0, 1, 3},
            "verify": {0, 1, 3, 4},
            "dispute": {0, 1, 3, 4},
            "extension-create": {0, 1, 3},
            "extension-accept": {0, 1, 3, 4},
            "extension-reject": {0, 1, 3, 4},
        }
        assert set(locks) == expected[action]
        distinct = list(dict.fromkeys(users))
        assert distinct == sorted([b10.users["A"], b10.users["B"]])
    elif action == "summary":
        assert locks == [1]  # summary must not lock every financial parent
    elif action == "deactivate":
        assert set(locks) == {1}
    else:
        assert locks == [1, 2]
