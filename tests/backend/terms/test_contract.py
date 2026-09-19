from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from app.main import create_app
from app.models.commitment_terms_version import CommitmentTermsVersion
from app.models.user import User
from sqlalchemy import select

from .conftest import create

BASE = "/api/v1/commitments"
VERSION_FIELDS = {
    "id",
    "version_no",
    "effective_at",
    "due_date",
    "interest_type",
    "interest_rate_bps",
    "grace_period_days",
    "schedule_mode",
    "due_timezone",
    "installment_dates",
    "created_by",
    "created_at",
}
INSTALLMENT_FIELDS = {
    "id",
    "terms_version_id",
    "sequence_no",
    "due_date",
    "principal_amount_minor",
    "interest_amount_minor",
    "total_due_minor",
    "currency",
    "status",
    "created_at",
    "updated_at",
}


@pytest.mark.parametrize("mode", ["legacy", "none", "single", "installments"])
@pytest.mark.parametrize("currency", ["INR", "USD", "GBP"])
def test_read_contract(b6, mode, currency):
    values = None if mode == "legacy" else {"interest_type": "NONE"}
    if mode == "single":
        values["due_date"] = "2024-02-29"
    if mode == "installments":
        values = b6.terms
    identifier = create(b6, values, currency=currency)
    response = b6.request("GET", f"/{identifier}/terms")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"commitment_id", "currency", "current_terms_version_id", "versions"}
    assert body["currency"] == currency and body["commitment_id"] == identifier
    version = body["versions"][0]
    assert set(version) == VERSION_FIELDS
    assert version["id"] == body["current_terms_version_id"]
    assert version["schedule_mode"] == ("none" if mode == "legacy" else mode)
    assert set(version["created_by"]) == {"id", "display_name"}
    assert version["created_by"]["id"] == str(b6.users["A"])
    assert version["created_at"].endswith("Z") and version["effective_at"].endswith("Z")
    assert (
        version["installment_dates"] is None
        if mode != "installments"
        else version["installment_dates"] == b6.terms["installment_dates"]
    )
    rows = b6.request("GET", f"/{identifier}/installments")
    assert rows.status_code == 200
    if mode != "installments":
        assert rows.json() == []
    else:
        assert [r["sequence_no"] for r in rows.json()] == [1, 2, 3]
        for r in rows.json():
            assert set(r) == INSTALLMENT_FIELDS
            assert r["currency"] == currency and r["terms_version_id"] == version["id"]
            assert r["status"] == "PENDING"
    for r in (response, rows):
        assert "schedule_definition" not in r.text
        assert all(phone not in r.text for phone in b6.phones.values())
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["X-Request-ID"]
    if mode == "legacy":
        assert version["due_timezone"] is None
        with b6.api.factory() as db:
            stored = db.scalar(
                select(CommitmentTermsVersion).where(
                    CommitmentTermsVersion.commitment_id == UUID(identifier)
                )
            )
            assert stored.schedule_definition is stored.due_date is stored.interest_rate_bps is None
            assert stored.interest_type.value == "NONE" and stored.grace_period_days == 0


@pytest.mark.parametrize("suffix", ["terms", "installments"])
@pytest.mark.parametrize("actor", ["A", "B", "C"])
def test_participant_access(b6, suffix, actor):
    identifier = create(b6, b6.terms)
    # C has a real connection to A, which must not grant this history.
    connection = b6.call("POST", actor="C", json={"phone": b6.phones["A"]}).json()["id"]
    assert b6.call("POST", "/" + connection + "/accept", actor="A").status_code == 200
    response = b6.request("GET", f"/{identifier}/{suffix}", actor=actor)
    assert response.status_code == (404 if actor == "C" else 200)
    if actor == "C":
        assert response.json() == {
            "error": {"code": "NOT_FOUND", "message": "Unavailable resource."}
        }


@pytest.mark.parametrize("suffix", ["terms", "installments"])
@pytest.mark.parametrize("change", ["block", "remove"])
def test_connection_change_preserves_access(b6, suffix, change):
    identifier = create(b6, b6.terms)
    response = b6.call(
        "POST" if change == "block" else "DELETE",
        "/" + b6.connection + ("/block" if change == "block" else ""),
    )
    assert response.status_code == 200
    for actor in "AB":
        assert b6.request("GET", f"/{identifier}/{suffix}", actor=actor).status_code == 200


@pytest.mark.parametrize("suffix", ["terms", "installments"])
def test_missing_and_auth(b6, suffix):
    assert b6.request("GET", f"/{uuid4()}/{suffix}").status_code == 404
    assert b6.request("GET", f"/bad/{suffix}").status_code == 422
    response = b6.api.client.get(f"{BASE}/{uuid4()}/{suffix}")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("actor_role,borrower", [("BORROWER", "A"), ("LENDER", "B")])
def test_timezone_snapshot(b6, actor_role, borrower):
    with b6.api.factory.begin() as db:
        db.get(User, b6.users["A"]).timezone = "Asia/Kolkata"
        db.get(User, b6.users["B"]).timezone = "America/New_York"
    identifier = create(b6, b6.terms, actor_role=actor_role)
    first = b6.request("GET", f"/{identifier}/terms").json()
    assert first["versions"][0]["due_timezone"] == (
        "Asia/Kolkata" if borrower == "A" else "America/New_York"
    )
    assert (
        b6.api.client.patch(
            "/api/v1/me", headers=b6.headers[borrower], json={"timezone": "Europe/London"}
        ).status_code
        == 200
    )
    assert b6.request("GET", f"/{identifier}/terms").json() == first


def test_exact_openapi():
    schema = create_app().openapi()
    models = schema["components"]["schemas"]
    paths = {path: set(ops) for path, ops in schema["paths"].items() if path.startswith(BASE)}
    assert paths == {
        BASE: {"get", "post"},
        BASE + "/{id}": {"get"},
        **{BASE + "/{id}/" + a: {"post"} for a in ("confirm", "reject", "cancel")},
        **{BASE + "/{id}/" + a: {"get"} for a in ("terms", "installments")},
        BASE + "/{id}/repayments": {"get", "post"},
    }
    assert "terms" not in models["CommitmentRequest"]["required"]
    assert models["CommitmentRequest"]["properties"]["terms"]["$ref"].endswith("TermsRequest")
    assert set(models["TermsRequest"]["properties"]) == {
        "due_date",
        "interest_type",
        "interest_rate_bps",
        "grace_period_days",
        "installment_dates",
    }
    for name in ("TermsRequest", "TermsResponse", "TermsVersionResponse", "InstallmentResponse"):
        assert models[name]["additionalProperties"] is False
    assert set(models["TermsVersionResponse"]["properties"]) == VERSION_FIELDS
    assert set(models["InstallmentResponse"]["properties"]) == INSTALLMENT_FIELDS
    for suffix in ("terms", "installments"):
        op = schema["paths"][BASE + "/{id}/" + suffix]["get"]
        assert op["security"] == [{"HTTPBearer": []}]
        assert not any(p["name"] == "Idempotency-Key" for p in op["parameters"])
        for code in ("401", "404", "422", "500", "503"):
            assert op["responses"][code]["content"]["application/json"]["schema"]["$ref"].endswith(
                "AuthErrorEnvelope"
            )


@pytest.mark.parametrize(
    "terms",
    [
        None,
        {},
        {"interest_type": "none"},
        {"interest_type": "SIMPLE_FIXED", "interest_rate_bps": True},
        {"interest_type": "NONE", "due_date": "2026-02-30"},
        {"interest_type": "NONE", "currency": "USD"},
        {"interest_type": "NONE", "grace_period_days": "1"},
    ],
)
def test_http_validation(b6, terms):
    response = b6.request("POST", json={**b6.body, "terms": terms})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "dates",
    [
        ["2024-02-29", "2026-09-11", "2027-01-01"],
        ["2026-12-31", "2027-01-01"],
        [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(60)],
    ],
)
def test_calendar_dates_and_count_persist_without_overdue_transition(b6, dates):
    identifier = create(b6, {"interest_type": "NONE", "installment_dates": dates})
    rows = b6.request("GET", f"/{identifier}/installments").json()
    assert [r["due_date"] for r in rows] == dates
    assert all(r["status"] == "PENDING" for r in rows)


@pytest.mark.parametrize("action,actor", [("confirm", "B"), ("reject", "B"), ("cancel", "A")])
def test_b5_lifecycle_preserves_terms_and_installments(b6, action, actor):
    identifier = create(b6, b6.terms)
    before = [b6.request("GET", f"/{identifier}/{s}").json() for s in ("terms", "installments")]
    assert b6.request("POST", f"/{identifier}/{action}", actor=actor).status_code == 200
    assert [
        b6.request("GET", f"/{identifier}/{s}").json() for s in ("terms", "installments")
    ] == before
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        assert b6.request(method, f"/{identifier}/terms", json={}).status_code == 405
