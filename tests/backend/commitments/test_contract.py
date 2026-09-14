from uuid import uuid4

import pytest
from app.main import create_app

from .test_lifecycle import create

BASE = "/api/v1/commitments"
ROUTES = [
    ("POST", ""),
    ("GET", ""),
    ("GET", "/{id}"),
    ("POST", "/{id}/confirm"),
    ("POST", "/{id}/reject"),
    ("POST", "/{id}/cancel"),
]


@pytest.mark.parametrize("amount", [None, False, True, 0, -1, 1.0, 1.5, "100", 1000000000001])
def test_invalid_amount(ctx, amount):
    r = ctx.request("POST", json={**ctx.body, "principal_amount_minor": amount})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_AMOUNT"


def test_missing_amount(ctx):
    body = dict(ctx.body)
    del body["principal_amount_minor"]
    r = ctx.request("POST", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_AMOUNT"


@pytest.mark.parametrize("amount", [1, 1000000000000])
def test_amount_boundaries(ctx, amount):
    assert create(ctx, principal_amount_minor=amount)["principal_amount_minor"] == amount


@pytest.mark.parametrize("currency", ["inr", "usd", "gbp", "EUR", " INR", "INR ", "", None, 123])
def test_invalid_currency(ctx, currency):
    r = ctx.request("POST", json={**ctx.body, "currency": currency})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "description,expected",
    [(None, None), ("", None), ("  ", None), ("  note  ", "note"), ("x" * 500, "x" * 500)],
)
def test_description(ctx, description, expected):
    assert create(ctx, description=description)["description"] == expected


@pytest.mark.parametrize("description", ["x" * 501, 42, True, [], {}])
def test_invalid_description(ctx, description):
    assert ctx.request("POST", json={**ctx.body, "description": description}).status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        "borrower_id",
        "lender_id",
        "counterparty_id",
        "phone",
        "status",
        "due_date",
        "interest_rate",
        "creator_id",
    ],
)
def test_overposting(ctx, field):
    assert ctx.request("POST", json={**ctx.body, field: "injected"}).status_code == 422


@pytest.mark.parametrize("method,path", ROUTES)
def test_ordinary_auth(ctx, method, path):
    r = ctx.api.client.request(
        method,
        BASE + path.replace("{id}", str(uuid4())),
        headers={"Idempotency-Key": "key"},
        json=ctx.body if not path else {},
    )
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert r.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("action", ["confirm", "reject", "cancel"])
def test_actions_closed_and_malformed(ctx, action):
    row = create(ctx)
    path = "/" + row["id"] + "/" + action
    assert ctx.request("POST", path, json={"reason": "no"}).status_code == 422
    assert ctx.request("POST", path, content="{").status_code == 400


def test_privacy_and_exact_response(ctx):
    row = create(ctx)
    expected = {
        "id",
        "connection_id",
        "type",
        "status",
        "principal_amount_minor",
        "currency",
        "description",
        "borrower",
        "lender",
        "creator",
        "created_at",
        "updated_at",
        "confirmed_at",
        "activated_at",
    }
    assert set(row) == expected
    for field in ("borrower", "lender", "creator"):
        assert set(row[field]) == {"id", "display_name"}
    response = ctx.request("GET", "/" + row["id"])
    assert response.json() == row
    assert all(phone not in response.text for phone in ctx.phones.values())
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]
    assert row["created_at"].endswith("Z")


def test_exact_openapi():
    schema = create_app().openapi()
    operations = {
        (m.upper(), p[len(BASE) :])
        for p, item in schema["paths"].items()
        if p.startswith(BASE)
        for m in item
    }
    assert operations == set(ROUTES) | {("GET", "/{id}/terms"), ("GET", "/{id}/installments")}
    models = schema["components"]["schemas"]
    request = models["CommitmentRequest"]
    assert request["additionalProperties"] is False
    assert set(request["properties"]) == {
        "connection_id",
        "actor_role",
        "type",
        "principal_amount_minor",
        "currency",
        "description",
        "terms",
    }
    assert request["properties"]["currency"]["enum"] == ["INR", "USD", "GBP"]
    for method, path in ROUTES:
        op = schema["paths"][BASE + path][method.lower()]
        assert op["security"] == [{"HTTPBearer": []}]
        if method == "POST":
            key = next(p for p in op["parameters"] if p["name"] == "Idempotency-Key")
            assert key["required"] and key["schema"]["maxLength"] == 128
        for code in ("400", "401", "403", "404", "409", "422", "500", "503"):
            assert op["responses"][code]["content"]["application/json"]["schema"]["$ref"].endswith(
                "AuthErrorEnvelope"
            )
