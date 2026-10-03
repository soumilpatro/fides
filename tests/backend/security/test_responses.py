import pytest

HOSTS = ["audit.invalid/abc?bar=", "audit.invalid?hidden=", "audit.invalid#hidden"]


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize(
    "case", ["success", "malformed", "auth", "unavailable", "validation", "failure", "rate"]
)
def test_host_invariant_response_policy(security_client, host, case):
    headers = {"Host": host, "X-Request-ID": "security-id"}
    if case == "success":
        headers["Authorization"] = "Bearer audit-test-only"
        response = security_client.get("/api/v1/me", headers=headers)
        status, code = 200, None
    elif case in {"malformed", "validation"}:
        content = "{" if case == "malformed" else '{"intent":"signup","phone":123}'
        response = security_client.post(
            "/api/v1/auth/otp/request",
            content=content,
            headers={**headers, "Content-Type": "application/json"},
        )
        status, code = (
            (400, "MALFORMED_REQUEST") if case == "malformed" else (422, "VALIDATION_ERROR")
        )
    elif case == "auth":
        response = security_client.get("/api/v1/me", headers=headers)
        status, code = 401, "AUTH_REQUIRED"
        assert response.headers["www-authenticate"] == "Bearer"
    else:
        suffix = {"unavailable": "unavailable", "failure": "failure", "rate": "rate-limit"}[case]
        response = security_client.get("/api/v1/auth/security-test/" + suffix, headers=headers)
        status, code = {
            "unavailable": (404, "NOT_FOUND"),
            "failure": (500, "INTERNAL_ERROR"),
            "rate": (429, "OTP_RATE_LIMITED"),
        }[case]
    assert response.status_code == status
    if code:
        assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "security-id"
    assert response.headers.get_list("x-content-type-options") == ["nosniff"]
    assert response.headers.get_list("referrer-policy") == ["no-referrer"]
    if case == "rate":
        assert response.headers["retry-after"] == "60"
    assert "B14-SYNTHETIC-SECRET-SENTINEL" not in response.text
    for unwanted in (
        "content-security-policy",
        "x-frame-options",
        "strict-transport-security",
        "permissions-policy",
    ):
        assert unwanted not in response.headers


def test_cors_remains_restrictive(security_client):
    response = security_client.options(
        "/api/v1/auth/refresh",
        headers={
            "Origin": "https://untrusted.invalid",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_host_cannot_reclassify_invalid_phone(security_client):
    for host in HOSTS:
        response = security_client.post(
            "/api/v1/auth/otp/request",
            json={"intent": "signup", "phone": "invalid"},
            headers={"Host": host},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_PHONE"


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("repayment", [False, True])
def test_host_cannot_reclassify_financial_amount(security_client, host, repayment):
    if repayment:
        path = "/api/v1/commitments/security-test/amount/repayments"
        body = {"amount_minor": 0, "currency": "INR", "payment_date": "2026-09-11"}
    else:
        path = "/api/v1/commitments/security-test/amount"
        body = {
            "connection_id": "12345678-1234-1234-1234-123456789abc",
            "actor_role": "BORROWER",
            "type": "IOU",
            "principal_amount_minor": 0,
            "currency": "INR",
        }
    response = security_client.post(path, json=body, headers={"Host": host})
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "INVALID_AMOUNT", "message": "Invalid amount."}}
    assert response.headers["cache-control"] == "no-store"
