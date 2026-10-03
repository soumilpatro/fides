import base64
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from .conftest import items


@pytest.mark.parametrize("limit", [1, 50, 100])
def test_order_and_pages(occ, limit):
    ids = occ.bulk(104)
    expected = sorted([occ.identifier] + [str(i) for i in ids])
    seen = []
    params = {"limit": limit}
    for _ in range(110):
        result = occ.query(params=params)
        rows = items(result)
        seen.extend(r["commitment_id"] for r in rows)
        cursor = result.json()["next_cursor"]
        if cursor is None:
            break
        params["cursor"] = cursor
    assert len(seen) == 105 and len(set(seen)) == 105
    assert seen == expected


def test_default_limit(occ):
    occ.bulk(60)
    assert len(items(occ.query())) == 50


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
def test_short_page_advances_past_filtered_candidates(occ, kind):
    occ.configure(due="2026-09-01" if kind == "overdue" else "2026-09-11")
    zero = occ.bulk(501, due="2026-09-02" if kind == "overdue" else "2026-09-12", zero=True)
    first = occ.query(kind)
    assert len(items(first)) == 1 and first.json()["next_cursor"]
    token = first.json()["next_cursor"]
    parts = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert parts[4] == str(sorted(zero)[498])
    last = occ.query(kind, params={"cursor": token})
    assert items(last) == [] and last.json()["next_cursor"] is None


@pytest.mark.parametrize("kind", ["upcoming", "overdue"])
def test_global_installment_and_parent_order(occ, kind):
    from app.models.commitment_installment import CommitmentInstallment
    from sqlalchemy import select

    occ.configure(due="2026-09-09" if kind == "overdue" else "2026-09-12")
    dates = ["2026-09-08", "2026-09-09"] if kind == "overdue" else ["2026-09-11", "2026-09-12"]
    parents = [
        occ.commitment(terms={"interest_type": "NONE", "installment_dates": dates})
        for _ in range(2)
    ]
    with occ.api.factory() as db:
        children = list(
            db.scalars(
                select(CommitmentInstallment).where(
                    CommitmentInstallment.commitment_id.in_([UUID(i) for i in parents])
                )
            )
        )
    expected = sorted(
        [(r.due_date.isoformat(), str(r.commitment_id), str(r.id)) for r in children]
        + [("2026-09-09" if kind == "overdue" else "2026-09-12", occ.identifier, "")]
    )
    seen, params = [], {"limit": 1}
    for _ in range(6):
        response = occ.query(kind, params=params)
        seen.extend(
            (r["due_date"], r["commitment_id"], r["installment_id"] or "") for r in items(response)
        )
        token = response.json()["next_cursor"]
        if token is None:
            break
        params["cursor"] = token
    assert seen == expected and token is None


@pytest.mark.parametrize("limit", ["0", "-1", "101", "1.0", "1e1", "true", "١", "", " 1"])
def test_invalid_limit(occ, limit):
    result = occ.query(params={"limit": limit})
    assert result.status_code == 422 and result.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("value", ["", "!", "a", "x" * 513, "e30", "W10", "bnVsbA"])
def test_bad_cursor(occ, value):
    assert occ.query(params={"cursor": value}).status_code == 422


@pytest.mark.parametrize(
    "index,value",
    [
        (0, True),
        (0, 2),
        (1, str(uuid4())),
        (1, "ABC"),
        (2, "OVERDUE"),
        (2, "upcoming"),
        (3, "20260911"),
        (3, "2026-9-11"),
        (3, "2026-02-30"),
        (4, "notuuid"),
        (4, 123),
        (5, False),
        (5, "bad"),
    ],
)
def test_cursor_fields(occ, index, value):
    parts = [1, str(occ.users["A"]), "UPCOMING", "2026-09-11", occ.identifier, None]
    parts[index] = value
    value = base64.urlsafe_b64encode(json.dumps(parts).encode()).decode().rstrip("=")
    assert occ.query(params={"cursor": value}).status_code == 422


def test_noncanonical_uuid_and_scope(occ):
    occ.bulk(1)
    cursor = occ.query(params={"limit": 1}).json()["next_cursor"]
    assert occ.query("upcoming", "B", params={"cursor": cursor}).status_code == 422
    assert occ.query("overdue", params={"cursor": cursor}).status_code == 422
    parts = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    for index in (1, 4):
        changed = list(parts)
        changed[index] = "{" + changed[index] + "}"
        token = base64.urlsafe_b64encode(json.dumps(changed).encode()).decode().rstrip("=")
        assert occ.query(params={"cursor": token}).status_code == 422


def test_scan_budget_empty_continuation(occ, monkeypatch):
    import app.summary_occurrences as service

    original, loaded = service.load_inputs, []

    def observe(db, ids, *args):
        loaded.append(len(ids))
        return original(db, ids, *args)

    monkeypatch.setattr(service, "load_inputs", observe)
    occ.configure(due="2026-09-12")
    zero_ids = occ.bulk(502, due="2026-09-11", zero=True)
    first = occ.query()
    assert items(first) == [] and first.json()["next_cursor"]
    token = first.json()["next_cursor"]
    decoded = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert decoded[3:] == ["2026-09-11", str(sorted(zero_ids)[499]), None]
    assert loaded == [500]
    last = occ.query(params={"cursor": token})
    assert len(items(last)) == 1 and last.json()["next_cursor"] is None
    assert loaded == [500, 3]


def test_short_filtered_page_and_live_changes(occ):
    occ.configure(due="2026-09-12")
    occ.bulk(501, due="2026-09-11", zero=True)
    first = occ.query()
    assert first.json()["next_cursor"] and items(first) == []
    occ.configure(status="CLOSED")
    final = occ.query(params={"cursor": first.json()["next_cursor"]})
    assert items(final) == [] and final.json()["next_cursor"] is None


@pytest.mark.parametrize("count", [1, 20])
@pytest.mark.parametrize("mode", ["single", "installments"])
def test_batched_queries_and_no_writes(occ, count, mode):
    if mode == "single":
        occ.bulk(count)
    else:
        for _ in range(count):
            occ.commitment(
                terms={
                    "interest_type": "NONE",
                    "installment_dates": ["2026-09-11", "2026-09-12", "2026-09-13"],
                }
            )
    statements = []
    engine = occ.api.factory.kw["bind"]

    def observe(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert items(occ.query())
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(statements) <= 12
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements
    )
    assert all("FROM users" in s for s in statements if "FOR UPDATE" in s)
    assert sum("SUM(" in s.upper() for s in statements) == 1
    assert sum("occurrence_candidates" in s and "LIMIT" in s for s in statements) <= 2
