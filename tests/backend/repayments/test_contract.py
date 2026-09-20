from datetime import datetime
from uuid import uuid4

import pytest
from app.main import create_app
from app.models.user import User

FIELDS = {
    "id",
    "commitment_id",
    "reported_by",
    "amount_minor",
    "currency",
    "payment_date",
    "reported_at",
    "status",
    "note",
    "created_at",
}
COLLECTION = "/api/v1/commitments/{id}/repayments"
DETAIL = "/api/v1/repayments/{id}"


def test_openapi_exact_b7_contract():
    schema = create_app().openapi()
    paths = {
        p: {method for method, op in ops.items() if "Repayments" in op.get("tags", [])}
        for p, ops in schema["paths"].items()
        if any("Repayments" in op.get("tags", []) for op in ops.values())
    }
    assert paths == {COLLECTION: {"post", "get"}, DETAIL: {"get"}}
    assert not any(
        s in p for p in schema["paths"] for s in ("settlement", "waiver", "verify-repayment")
    )
    models = schema["components"]["schemas"]
    assert set(models["RepaymentResponse"]["properties"]) == FIELDS
    assert set(models["RepaymentResponse"]["required"]) == FIELDS
    assert set(models["RepaymentRequest"]["properties"]) == {
        "amount_minor",
        "currency",
        "payment_date",
        "note",
    }
    assert set(models["RepaymentRequest"]["required"]) == {
        "amount_minor",
        "currency",
        "payment_date",
    }
    assert "maximum" not in models["RepaymentRequest"]["properties"]["amount_minor"]
    for name in ("RepaymentRequest", "RepaymentResponse", "ParticipantResponse"):
        assert models[name]["additionalProperties"] is False
    for path, methods in paths.items():
        for method in methods:
            op = schema["paths"][path][method]
            assert op["security"] == [{"HTTPBearer": []}]
            keys = [p for p in op["parameters"] if p["name"] == "Idempotency-Key"]
            assert len(keys) == (1 if method == "post" else 0)
            if keys:
                assert keys[0]["required"] is True
            for code in (400, 401, 403, 404, 409, 422, 500, 503):
                assert str(code) in op["responses"]
            assert "OVER_REPAYMENT" in op["responses"]["409"]["description"]
            assert "CURRENCY_MISMATCH" in op["responses"]["422"]["description"]


def test_exact_http_response_and_no_pii(b7):
    result = b7.report(note="  private note  ")
    assert result.status_code == 201
    body = result.json()
    assert set(body) == FIELDS
    assert set(body["reported_by"]) == {"id", "display_name"}
    assert body["note"] == "private note"
    assert body["payment_date"] == "2026-09-11"
    for field in ("created_at", "reported_at"):
        assert datetime.fromisoformat(body[field]).utcoffset().total_seconds() == 0
    for phone in b7.phones.values():
        assert phone not in result.text


@pytest.mark.parametrize("amount", [True, False, 1.0, 1.5, "100", 0, -1, None, [], {}])
def test_invalid_amount(b7, amount):
    response = b7.report(amount_minor=amount)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_AMOUNT"


@pytest.mark.parametrize("field", ["amount_minor", "currency", "payment_date"])
def test_required_fields(b7, field):
    body = {k: v for k, v in b7.report_body.items() if k != field}
    response = b7.request("POST", f"/{b7.identifier}/repayments", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == (
        "INVALID_AMOUNT" if field == "amount_minor" else "VALIDATION_ERROR"
    )


@pytest.mark.parametrize(
    "field",
    [
        "commitment_id",
        "principal_amount_minor",
        "reported_by_user_id",
        "reporter",
        "verifier_id",
        "status",
        "balance",
        "outstanding",
        "installment_id",
        "terms_version_id",
        "idempotency_key_id",
        "method",
        "reference",
        "evidence",
    ],
)
def test_overposting(b7, field):
    result = b7.report(**{field: "private"})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("currency", ["inr", " InR ", "EUR", None, 123])
def test_bad_currency(b7, currency):
    assert b7.report(currency=currency).status_code == 422


@pytest.mark.parametrize(
    "note,valid,normalized",
    [
        (None, True, None),
        ("", True, None),
        ("  ", True, None),
        (" x ", True, "x"),
        ("x" * 500, True, "x" * 500),
        ("x" * 501, False, None),
        (12, False, None),
        (False, False, None),
    ],
)
def test_notes(b7, note, valid, normalized):
    result = b7.report(note=note)
    assert result.status_code == (201 if valid else 422)
    if valid:
        assert result.json()["note"] == normalized


@pytest.mark.parametrize(
    "value,valid",
    [
        ("2024-02-29", True),
        ("2026-09-10", True),
        ("2026-09-11", True),
        ("2026-09-12", False),
        ("2025-02-29", False),
        ("2026-9-1", False),
        ("2026-09-11T00:00:00Z", False),
        ("20260911", False),
        (1789084800, False),
        (None, False),
    ],
)
def test_payment_dates(b7, value, valid):
    result = b7.report(payment_date=value)
    assert result.status_code == (201 if valid else 422)
    if valid:
        assert result.json()["payment_date"] == value
    else:
        assert result.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "timezone,date,valid",
    [
        ("Pacific/Kiritimati", "2026-09-12", True),
        ("America/Los_Angeles", "2026-09-12", False),
        ("UTC", "2026-09-11", True),
    ],
)
def test_reporter_timezone_boundary(b7, timezone, date, valid):
    # Existing clock is noon UTC; Kiritimati is already on the next calendar day.
    with b7.api.factory.begin() as db:
        db.get(User, b7.users["B"]).timezone = timezone
    result = b7.report(actor="B", payment_date=date)
    assert result.status_code == (201 if valid else 422)


@pytest.mark.parametrize(
    "method,path", [("post", COLLECTION), ("get", COLLECTION), ("get", DETAIL)]
)
def test_authentication_and_no_store(b7, method, path):
    response = b7.api.client.request(method, path.format(id=b7.identifier), json=b7.report_body)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("case", ["success", "missing", "invalid_id", "malformed", "unexpected"])
def test_headers_safe_errors(b7, case, monkeypatch):
    from app.repayments import RepaymentService

    headers = {**b7.headers["A"], "X-Request-ID": "bad id private", "Idempotency-Key": uuid4().hex}
    if case == "malformed":
        result = b7.api.client.post(
            COLLECTION.format(id=b7.identifier),
            headers=headers,
            content="{",
        )
        assert result.status_code == 400
    else:
        identifier = b7.report().json()["id"]
        if case == "unexpected":

            def fail(*args, **kwargs):
                raise RuntimeError("private internal data")

            monkeypatch.setattr(RepaymentService, "read", fail)
        result = b7.api.client.get(
            DETAIL.format(
                id=identifier
                if case in ("success", "unexpected")
                else "bad"
                if case == "invalid_id"
                else uuid4()
            ),
            headers=headers,
        )
        assert (
            result.status_code
            == {"success": 200, "missing": 404, "invalid_id": 422, "unexpected": 500}[case]
        )
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Request-ID"] != "bad id private"
    assert "private" not in result.text


@pytest.mark.parametrize("key", [None, "", "a b", "x" * 129, "with/slash"])
def test_required_valid_idempotency_header(b7, key):
    headers = dict(b7.headers["A"])
    if key is not None:
        headers["Idempotency-Key"] = key
    result = b7.api.client.post(
        COLLECTION.format(id=b7.identifier), headers=headers, json=b7.report_body
    )
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_huge_integer_is_capacity_error_not_database_overflow(b7):
    result = b7.report(amount_minor=2**100)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "OVER_REPAYMENT"


def test_duplicate_idempotency_header(b7):
    headers = list(b7.headers["A"].items()) + [
        ("Idempotency-Key", "one"),
        ("Idempotency-Key", "two"),
    ]
    result = b7.api.client.post(
        COLLECTION.format(id=b7.identifier), headers=headers, json=b7.report_body
    )
    assert result.status_code == 400


def test_invalid_stored_timezone_fails_safely(b7):
    with b7.api.factory.begin() as db:
        db.get(User, b7.users["A"]).timezone = "invalid/zone"
    result = b7.report()
    assert result.status_code == 503
    assert "invalid/zone" not in result.text
