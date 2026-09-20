from datetime import datetime
from uuid import uuid4

import pytest
from app.main import create_app

from repayments.test_contract import FIELDS

BASE = "/api/v1/repayments/{id}"
HISTORY_FIELDS = {"id", "repayment_id", "decided_by", "decision", "decision_note", "decided_at"}


def test_exact_openapi_contract():
    schema = create_app().openapi()
    paths = {p: set(ops) for p, ops in schema["paths"].items() if "repayments" in p}
    assert paths == {
        "/api/v1/commitments/{id}/repayments": {"get", "post"},
        BASE: {"get"},
        BASE + "/verify": {"post"},
        BASE + "/dispute": {"post"},
        BASE + "/verification-history": {"get"},
    }
    assert not any(
        word in p
        for p in schema["paths"]
        for word in (
            "settlement",
            "waiver",
            "evidence",
            "allocation",
            "/verifications",
            "/ledger",
            "/extensions",
        )
    )
    models = schema["components"]["schemas"]
    assert set(models["DecisionRequest"]["properties"]) == {"decision_note"}
    assert not models["DecisionRequest"].get("required")
    assert set(models["VerificationResponse"]["properties"]) == HISTORY_FIELDS
    assert set(models["VerificationResponse"]["required"]) == HISTORY_FIELDS
    for name in (
        "DecisionRequest",
        "VerificationResponse",
        "RepaymentResponse",
        "ParticipantResponse",
    ):
        assert models[name]["additionalProperties"] is False
    assert models["VerificationDecision"]["enum"] == ["VERIFIED", "DISPUTED"]
    for action in ("verify", "dispute", "verification-history"):
        method = "get" if action == "verification-history" else "post"
        op = schema["paths"][BASE + "/" + action][method]
        assert op["security"] == [{"HTTPBearer": []}]
        assert {p["name"] for p in op["parameters"]} == (
            {"id"} if method == "get" else {"id", "Idempotency-Key"}
        )
        if method == "post":
            assert next(p for p in op["parameters"] if p["name"] == "Idempotency-Key")["required"]
            assert op["requestBody"]["required"]
            assert op["requestBody"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/DecisionRequest"
            }
        response = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert response == (
            {"$ref": "#/components/schemas/RepaymentResponse"}
            if method == "post"
            else {
                "type": "array",
                "items": {"$ref": "#/components/schemas/VerificationResponse"},
                "title": response["title"],
            }
        )
        for code in (400, 401, 403, 404, 409, 422, 500, 503):
            assert str(code) in op["responses"]
        for code in (
            "ALREADY_VERIFIED",
            "OVER_REPAYMENT",
            "INVALID_STATE",
            "IDEMPOTENCY_CONFLICT",
            "CONFLICT",
        ):
            assert code in op["responses"]["409"]["description"]
        assert op["responses"]["422"]["description"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("action", ["verify", "dispute"])
@pytest.mark.parametrize(
    "note,valid,expected",
    [
        (None, True, None),
        ("", True, None),
        (" \t ", True, None),
        (" hi ", True, "hi"),
        (" " + "x" * 500 + " ", True, "x" * 500),
        ("x" * 501, False, None),
        (123, False, None),
        (False, False, None),
        ([], False, None),
        ({}, False, None),
    ],
)
def test_note_contract(b8, action, note, valid, expected):
    result = b8.decide(action, body={"decision_note": note})
    assert result.status_code == (200 if valid else 422)
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Request-ID"]
    if not valid:
        assert result.json()["error"]["code"] == "VALIDATION_ERROR"
        assert b8.history().json() == []
        return
    assert set(result.json()) == FIELDS
    assert set(result.json()["reported_by"]) == {"id", "display_name"}
    history = b8.history().json()
    assert len(history) == 1 and set(history[0]) == HISTORY_FIELDS
    assert set(history[0]["decided_by"]) == {"id", "display_name"}
    assert history[0]["decision_note"] == expected
    assert history[0]["repayment_id"] == b8.repayment
    assert datetime.fromisoformat(history[0]["decided_at"]).utcoffset().total_seconds() == 0
    for phone in b8.phones.values():
        assert phone not in result.text + b8.history().text


@pytest.mark.parametrize("action", ["verify", "dispute"])
@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "decided_by_user_id",
        "repayment_id",
        "commitment_id",
        "status",
        "decision",
        "decided_at",
        "amount_minor",
        "currency",
        "terms_version_id",
        "balance",
        "outstanding",
        "evidence",
        "payment_method",
        "reference",
        "reason_code",
        "idempotency_key_id",
    ],
)
def test_overposting_rejected(b8, action, field):
    result = b8.decide(action, body={field: "private"})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "private" not in result.text


@pytest.mark.parametrize("action", ["verify", "dispute"])
@pytest.mark.parametrize("key", ["a", "x" * 128, "azAZ09._:-"])
def test_valid_key_boundaries_and_empty_body(b8, action, key):
    assert b8.decide(action, key=key).status_code == 200
    assert b8.decide(action, key=key, body={"decision_note": None}).status_code == 200
    assert len(b8.history().json()) == 1


@pytest.mark.parametrize("action", ["verify", "dispute"])
@pytest.mark.parametrize("key", [None, "", "a b", "x" * 129, "with/slash", "duplicate"])
def test_invalid_idempotency_header(b8, action, key):
    headers = list(b8.headers["B"].items())
    if key is not None:
        headers.append(("Idempotency-Key", key))
    if key == "duplicate":
        headers.append(("Idempotency-Key", "other"))
    result = b8.api.client.post(
        BASE.format(id=b8.repayment) + "/" + action, headers=headers, json={}
    )
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "MALFORMED_REQUEST"


@pytest.mark.parametrize("action", ["verify", "dispute"])
@pytest.mark.parametrize(
    "content,status", [("{", 400), ("", 422), ("null", 422), ("[]", 422), ('"text"', 422)]
)
def test_malformed_or_non_object_body(b8, action, content, status):
    result = b8.api.client.post(
        BASE.format(id=b8.repayment) + "/" + action,
        content=content,
        headers={
            **b8.headers["B"],
            "Idempotency-Key": uuid4().hex,
            "Content-Type": "application/json",
        },
    )
    assert result.status_code == status


@pytest.mark.parametrize("action", ["verify", "dispute", "verification-history"])
def test_authentication_headers(b8, action):
    result = b8.api.client.request(
        "GET" if action == "verification-history" else "POST",
        BASE.format(id=b8.repayment) + "/" + action,
        json={},
    )
    assert result.status_code == 401
    assert result.headers["WWW-Authenticate"] == "Bearer"
    assert result.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("case", ["success", "missing", "invalid_id", "unexpected"])
def test_safe_http_errors_and_request_id(b8, case, monkeypatch):
    from app.verification import VerificationService

    if case == "unexpected":

        def fail(*args, **kwargs):
            raise RuntimeError("private internal data")

        monkeypatch.setattr(VerificationService, "history", fail)
    result = b8.api.client.get(
        BASE.format(
            id=uuid4() if case == "missing" else "bad" if case == "invalid_id" else b8.repayment
        )
        + "/verification-history",
        headers={**b8.headers["B"], "X-Request-ID": "bad id private"},
    )
    assert (
        result.status_code
        == {"success": 200, "missing": 404, "invalid_id": 422, "unexpected": 500}[case]
    )
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Request-ID"] != "bad id private"
    assert "private" not in result.text
