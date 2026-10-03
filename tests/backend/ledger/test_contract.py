from uuid import uuid4

import pytest
from app.main import create_app
from sqlalchemy import event as sql_event

from .conftest import event
from .test_pagination import seed

PATH = "/api/v1/commitments/{id}/ledger"
COMMON = {"id", "commitment_id", "actor", "occurred_at", "event_type", "details"}
EXTENSION_DETAILS = {
    "extension_request_id",
    "base_terms_version_id",
    "requested_by_user_id",
    "previous_due_date",
    "requested_due_date",
    "status",
}
DETAILS = {
    **{
        f"MUTUAL_CLOSURE_{state}": {
            "closure_request_id",
            "status",
            "currency",
            "outstanding_snapshot_minor",
            "waived_amount_minor",
        }
        | ({"resulting_commitment_status"} if state == "ACCEPTED" else set())
        for state in ("REQUESTED", "ACCEPTED", "REJECTED", "CANCELLED")
    },
    "EXTENSION_REQUESTED": EXTENSION_DETAILS,
    "EXTENSION_REJECTED": EXTENSION_DETAILS,
    "EXTENSION_ACCEPTED": EXTENSION_DETAILS | {"terms_version_id"},
    "COMMITMENT_PROPOSED": {"status", "terms_version_id"},
    "COMMITMENT_CONFIRMED": {"status"},
    "COMMITMENT_REJECTED": {"status"},
    "COMMITMENT_CANCELLED": {"status"},
    "REPAYMENT_REPORTED": {
        "status",
        "repayment_id",
        "terms_version_id",
        "amount_minor",
        "currency",
    },
    "REPAYMENT_DISPUTED": {"status", "repayment_id", "verification_id", "amount_minor", "currency"},
    "REPAYMENT_VERIFIED": {
        "status",
        "repayment_id",
        "verification_id",
        "amount_minor",
        "currency",
        "terms_version_id",
        "resulting_verified_outstanding_minor",
        "resulting_commitment_status",
    },
}


def test_openapi_exact_contract():
    schema = create_app().openapi()
    assert {p: set(ops) for p, ops in schema["paths"].items() if "ledger" in p} == {PATH: {"get"}}
    op = schema["paths"][PATH]["get"]
    assert op["security"] == [{"HTTPBearer": []}]
    assert "requestBody" not in op
    params = {p["name"]: p for p in op["parameters"]}
    assert set(params) == {"id", "limit", "cursor"}
    assert params["limit"]["schema"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 100,
        "default": 50,
        "title": "Limit",
    }
    for status in [401, 404, 422, 500, 503]:
        response = op["responses"][str(status)]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith(
            "AuthErrorEnvelope"
        )
        assert "Cache-Control" in response["headers"]
    assert "409" not in op["responses"]
    models = schema["components"]["schemas"]
    assert set(models["LedgerResponse"]["properties"]) == {"items", "next_cursor"}
    union = models["LedgerResponse"]["properties"]["items"]["items"]
    assert union["discriminator"]["propertyName"] == "event_type"
    assert set(union["discriminator"]["mapping"]) == set(DETAILS)
    for variant in union["oneOf"]:
        model = models[variant["$ref"].split("/")[-1]]
        assert set(model["properties"]) == set(model["required"]) == COMMON
        assert model["additionalProperties"] is False
        event_type = model["properties"]["event_type"]["const"]
        detail = models[model["properties"]["details"]["$ref"].split("/")[-1]]
        assert set(detail["properties"]) == set(detail["required"]) == DETAILS[event_type]
        assert detail["additionalProperties"] is False


@pytest.mark.parametrize("suffix", ["/history", "/audit", "/ledger/" + str(uuid4())])
def test_no_other_commitment_history_routes(timeline, suffix):
    response = timeline.api.client.get(
        f"/api/v1/commitments/{timeline.identifier}" + suffix, headers=timeline.headers["A"]
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/audit",
        "/api/v1/audit-logs",
        "/api/v1/admin/audit",
        "/api/v1/ledger",
        "/api/v1/activity",
        "/api/v1/me/activity",
        "/api/v1/dashboard/activity",
    ],
)
def test_no_public_audit_or_global_resource(timeline, path):
    assert timeline.api.client.get(path, headers=timeline.headers["A"]).status_code == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_no_mutation_routes(timeline, method):
    assert (
        timeline.api.client.request(
            method,
            PATH.replace("{id}", timeline.identifier),
            headers=timeline.headers["A"],
            json={},
        ).status_code
        == 405
    )


@pytest.mark.parametrize("decision", ["verify", "dispute"])
def test_exact_fields_and_privacy(timeline, decision):
    assert timeline.decide(decision, body={"decision_note": "private-note"}).status_code == 200
    response = timeline.timeline()
    assert response.status_code == 200
    assert set(response.json()) == {"items", "next_cursor"}
    for item in response.json()["items"]:
        assert set(item) == COMMON
        assert set(item["details"]) == DETAILS[item["event_type"]]
        assert set(item["actor"]) == {"id", "display_name"}
        assert item["occurred_at"].endswith("Z")
    for forbidden in [
        "event_payload",
        "created_at",
        "request_id",
        "metadata",
        "phone",
        "private-note",
        "decision_note",
        "evidence",
        "idempotency",
        "object_type",
    ]:
        assert forbidden not in response.text
    for phone in timeline.phones.values():
        assert phone not in response.text


@pytest.mark.parametrize(
    "key", ["phone", "note", "evidence", "request_id", "idempotency_key", "unrelated_id"]
)
def test_extra_payload_fails_closed_without_leak(timeline, key):
    secret = "private-" + str(uuid4())
    with timeline.api.factory.begin() as db:
        row = event(db, timeline, "REPAYMENT_REPORTED")
        row.event_payload = {**row.event_payload, key: secret}
    response = timeline.timeline()
    assert response.status_code == 503
    assert secret not in response.text


@pytest.mark.parametrize("request_id", ["safe.correlation-123", "unsafe value!", "x" * 65])
def test_http_headers(timeline, request_id):
    path = PATH.replace("{id}", timeline.identifier)
    response = timeline.api.client.get(
        path, headers={**timeline.headers["A"], "X-Request-ID": request_id}
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    actual = response.headers["X-Request-ID"]
    assert actual == request_id if request_id == "safe.correlation-123" else actual != request_id


@pytest.mark.parametrize("token", [None, "bad"])
def test_authentication(timeline, token):
    response = timeline.api.client.get(
        PATH.replace("{id}", timeline.identifier),
        headers={} if token is None else {"Authorization": "Bearer " + token},
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"


def test_no_n_plus_one(timeline):
    counts = []
    engine = timeline.api.factory.kw["bind"]

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counts.append(statement)

    seed(timeline, 3)
    sql_event.listen(engine, "before_cursor_execute", record)
    try:
        assert timeline.timeline().status_code == 200
        small = len(counts)
        seed(timeline, 100)
        counts.clear()
        assert timeline.timeline(params={"limit": 100}).status_code == 200
        assert len(counts) == small
    finally:
        sql_event.remove(engine, "before_cursor_execute", record)
