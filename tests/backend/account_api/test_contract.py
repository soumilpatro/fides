from datetime import timedelta

import pytest
from app.core.errors import AuthError
from app.main import create_app
from app.models.enums import UserStatus
from app.models.user import User
from auth_api.test_api import BASE, error

from .test_account import ME, call

PROTECTED = [("GET", ME), ("PATCH", ME), ("POST", ME + "/deactivate")]


@pytest.mark.parametrize("method,path", PROTECTED)
@pytest.mark.parametrize(
    "kind,code",
    [
        ("missing", "AUTH_REQUIRED"),
        ("malformed", "INVALID_AUTH_TOKEN"),
        ("duplicate", "INVALID_AUTH_TOKEN"),
        ("refresh", "INVALID_AUTH_TOKEN"),
        ("expired", "AUTH_TOKEN_EXPIRED"),
        ("revoked", "SESSION_REVOKED"),
        ("rotated", "INVALID_AUTH_TOKEN"),
        ("deactivated", "ACCOUNT_DEACTIVATED"),
        ("unavailable", "ACCOUNT_UNAVAILABLE"),
    ],
)
def test_ordinary_dependency_rejects_invalid_or_ineligible_access(
    account, method, path, kind, code
):
    api = account.api
    headers = account.headers
    if kind == "missing":
        headers = {}
    elif kind == "malformed":
        headers = {"Authorization": "Bearer bad"}
    elif kind == "duplicate":
        headers = [
            ("Authorization", account.headers["Authorization"]),
            ("Authorization", "Bearer bad"),
        ]
    elif kind == "refresh":
        headers = {"Authorization": "Bearer " + account.credentials["refresh_token"]}
    elif kind == "expired":
        api.clock.now += timedelta(minutes=15)
    elif kind == "revoked":
        api.service.revoke_one(api.service.recognize_logout(account.headers["Authorization"]))
    elif kind == "rotated":
        api.service.refresh(account.credentials["refresh_token"], ip="192.0.2.1")
    else:
        with api.factory.begin() as db:
            db.get(User, account.user_id).status = (
                UserStatus.DEACTIVATED if kind == "deactivated" else UserStatus.ANONYMIZED
            )
    response = api.client.request(
        method, path, headers=headers, json={"display_name": "Changed"} if method == "PATCH" else {}
    )
    error(response, code, 403 if kind in {"deactivated", "unavailable"} else 401)


def test_expired_access_still_only_logs_out(account):
    account.api.clock.now += timedelta(minutes=15)
    for method, path in PROTECTED:
        error(
            call(
                account, method, path, json={"display_name": "Changed"} if method == "PATCH" else {}
            ),
            "AUTH_TOKEN_EXPIRED",
            401,
        )
    assert call(account, "POST", BASE + "/logout").status_code == 200


@pytest.mark.parametrize("method,path", [("PATCH", ME), ("POST", ME + "/deactivate")])
@pytest.mark.parametrize(
    "raw,code,status",
    [
        ("{", "MALFORMED_REQUEST", 400),
        ("null", "VALIDATION_ERROR", 422),
        ('{"user_id":"private"}', "VALIDATION_ERROR", 422),
    ],
)
def test_actual_body_contract_and_safe_headers(account, method, path, raw, code, status):
    response = call(account, method, path, content=raw)
    error(response, code, status)
    assert "private" not in response.text


def test_seven_endpoint_openapi_and_closed_account_models():
    schema = create_app().openapi()
    operations = {
        (method.upper(), path)
        for path, item in schema["paths"].items()
        if path.startswith("/api/v1/")
        and not path.startswith(
            ("/api/v1/connections", "/api/v1/commitments", "/api/v1/repayments")
        )
        for method in item
    }
    assert operations == set(PROTECTED) | {
        ("POST", BASE + suffix) for suffix in ("/otp/request", "/otp/verify", "/refresh", "/logout")
    }
    for method, path in PROTECTED:
        item = schema["paths"][path][method.lower()]
        assert item["security"] == [{"HTTPBearer": []}]
        assert item["responses"]["401"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/AuthErrorEnvelope"
        }
        assert (
            item["responses"]["401"]["headers"]["WWW-Authenticate"]["schema"]["const"] == "Bearer"
        )
        assert item["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/"
            + ("DeactivationResponse" if method == "POST" else "MeResponse")
        }
    models = schema["components"]["schemas"]
    assert set(models["MeResponse"]["properties"]) == {
        "id",
        "phone_e164",
        "display_name",
        "timezone",
        "status",
        "created_at",
        "updated_at",
    }
    assert models["ProfileUpdateRequest"]["additionalProperties"] is False
    assert set(models["ProfileUpdateRequest"]["properties"]) == {"display_name", "timezone"}
    assert not any(
        name in str(models) for name in ("access_token_hash", "provider_reference", "_digest")
    )


def test_principal_is_not_logout_recognition_and_hides_digest(account):
    from app.auth.accounts import AccountService

    principal = account.api.service.resolve(account.headers["Authorization"])
    assert "digest" not in repr(principal) and account.credentials["access_token"] not in repr(
        principal
    )
    recognition = account.api.service.recognize_logout(account.headers["Authorization"])
    with pytest.raises(TypeError, match="Ordinary authenticated principal required"):
        AccountService(account.api.service).get(recognition)
    account.api.clock.now += timedelta(minutes=15)
    with pytest.raises(AuthError, match="AUTH_TOKEN_EXPIRED"):
        AccountService(account.api.service).get(principal)


def test_account_logs_and_audits_exclude_profile_and_credentials(account, caplog, monkeypatch):
    import logging

    from app.models.audit_log import AuditLog
    from auth_api.test_api import PHONE
    from sqlalchemy import select

    monkeypatch.setattr(logging.getLogger("sqlalchemy.engine.Engine"), "disabled", False)
    logging.getLogger().addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger="sqlalchemy.engine")
    response = call(account, "PATCH", json={"display_name": "Private Profile Name"})
    assert response.status_code == 200
    assert call(account, "POST", ME + "/deactivate").status_code == 200
    assert "Authentication I/O diagnostic redacted" in caplog.text
    with account.api.factory() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.actor_user_id == account.user_id)).all()
        metadata = str([row.metadata_ for row in logs])
    for secret in (
        PHONE,
        "Private Profile Name",
        account.credentials["access_token"],
        account.credentials["refresh_token"],
    ):
        assert secret not in caplog.text + metadata
