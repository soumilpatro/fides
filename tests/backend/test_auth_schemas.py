"""Closed wire contracts and reusable normalization, without authentication routes."""

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from app.api.auth_schemas import (
    CredentialResponse,
    DeactivationResponse,
    EmptyAuthRequest,
    LoginOtpVerifyRequest,
    LogoutResponse,
    MeResponse,
    OtpRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
    ProfileUpdateRequest,
    RefreshRequest,
    SignupOtpVerifyRequest,
)
from app.core.validation import normalize_display_name, normalize_phone, normalize_timezone
from pydantic import TypeAdapter, ValidationError


@pytest.mark.parametrize("phone", ["+919876543210", "+442083661177", "+16502532222"])
def test_international_phone_normalization(phone):
    assert normalize_phone("  " + phone + "  ") == phone


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        919876543210,
        "",
        "9876543210",
        "00919876543210",
        "+91 9876543210",
        "+91-9876543210",
        "+919876543210x1",
        "+919876543210;ext=1",
        "+01234",
        "+1234567890123456",
        "+12001230101",
        "+999123456",
        "+９１９８７６５４３２１０",
    ],
)
def test_phone_rejects_invalid_input(value):
    with pytest.raises(ValueError):
        normalize_phone(value)


@pytest.mark.parametrize("intent", ["signup", "login"])
def test_otp_request_exact_shape(intent):
    request = OtpRequest(intent=intent, phone=" +919876543210 ")
    assert request.model_dump() == {"intent": intent, "phone": "+919876543210"}


@pytest.mark.parametrize(
    "extra",
    [
        {"display_name": "Name"},
        {"timezone": "UTC"},
        {"display_name": None},
        {"user_id": str(uuid4())},
    ],
)
def test_otp_request_forbids_profile_and_unknown_fields(extra):
    with pytest.raises(ValidationError):
        OtpRequest(intent="signup", phone="+919876543210", **extra)


@pytest.mark.parametrize(
    "value",
    [
        123456,
        True,
        None,
        "12345",
        "1234567",
        " 123456",
        "123456\n",
        "１２３４５６",
        "١٢٣٤٥٦",
        "12a456",
    ],
)
def test_otp_requires_six_ascii_digits(value):
    with pytest.raises(ValidationError):
        LoginOtpVerifyRequest(challenge_id=uuid4(), code=value)


def test_verify_closed_variants_and_leading_zeros():
    adapter = TypeAdapter(OtpVerifyRequest)
    body = {"challenge_id": str(uuid4()), "code": "001234"}
    login = adapter.validate_json(json.dumps(body))
    assert type(login) is LoginOtpVerifyRequest
    assert login.code == "001234"
    signup = adapter.validate_python({**body, "display_name": "  Example  ", "timezone": "UTC"})
    assert type(signup) is SignupOtpVerifyRequest
    assert signup.display_name == "Example"
    for extra in (
        {"intent": "signup"},
        {"phone": "+919876543210"},
        {"user_id": str(uuid4())},
        {"display_name": "Name"},
        {"timezone": "UTC"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python({**body, **extra})
    with pytest.raises(ValidationError):
        LoginOtpVerifyRequest(**signup.model_dump())
    with pytest.raises(ValidationError):
        SignupOtpVerifyRequest(**body)


def test_profile_normalization_and_boundaries():
    assert normalize_display_name("  E\u0301X  Name  ") == "ÉX  Name"
    assert normalize_display_name("😀" * 100) == "😀" * 100
    assert normalize_display_name("e\u0301" * 100) == "é" * 100
    assert normalize_timezone(" UTC ") == "UTC"
    assert normalize_timezone("Asia/Kolkata") == "Asia/Kolkata"
    assert normalize_timezone("US/Eastern") == "US/Eastern"


@pytest.mark.parametrize(
    "value",
    [None, 123, True, "", "  ", "x" * 101, "name\n", "\tname", "na\x00me", "na\x7fme", "na\x85me"],
)
def test_invalid_display_name(value):
    with pytest.raises(ValueError):
        normalize_display_name(value)


@pytest.mark.parametrize(
    "value", [None, 123, True, "", " ", "x" * 65, "Unknown/Zone", "../UTC", "/UTC", "UTC\x00"]
)
def test_invalid_timezone(value):
    with pytest.raises(ValueError):
        normalize_timezone(value)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"display_name": None},
        {"timezone": None},
        {"display_name": 123},
        {"timezone": True},
        {"phone": "+919876543210"},
        {"status": "ACTIVE"},
    ],
)
def test_patch_rejects_empty_null_coercion_and_unknown_fields(body):
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(**body)


def test_patch_preserves_omission_and_normalizes():
    request = ProfileUpdateRequest(display_name=" E\u0301X ")
    assert request.model_dump(exclude_unset=True) == {"display_name": "ÉX"}
    assert request.model_fields_set == {"display_name"}
    assert ProfileUpdateRequest(timezone=" UTC ").model_dump(exclude_unset=True) == {
        "timezone": "UTC"
    }


@pytest.mark.parametrize(
    "model, body",
    [
        (OtpRequest, {"intent": "login", "phone": 919876543210}),
        (OtpRequest, {"intent": True, "phone": "+919876543210"}),
        (RefreshRequest, {"refresh_token": None}),
        (RefreshRequest, {"refresh_token": 123}),
        (RefreshRequest, {"refresh_token": True}),
        (RefreshRequest, {"refresh_token": ""}),
        (RefreshRequest, {"refresh_token": "x" * 513}),
        (RefreshRequest, {"refresh_token": "x", "access_token": "x"}),
        (EmptyAuthRequest, {"user_id": "x"}),
    ],
)
def test_other_closed_request_validation(model, body):
    with pytest.raises(ValidationError):
        model.model_validate(body)


def test_responses_have_exact_fields_and_utc_serialization():
    now = datetime(2026, 9, 10, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    user = MeResponse(
        id=uuid4(),
        phone_e164=None,
        display_name="Name",
        timezone="UTC",
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    credentials = CredentialResponse(
        access_token="test-only-access",
        refresh_token="test-only-refresh",
        token_type="Bearer",
        access_expires_at=now,
        refresh_expires_at=now,
        user=user,
    )
    body = credentials.model_dump(mode="json")
    assert set(body) == {
        "access_token",
        "refresh_token",
        "token_type",
        "access_expires_at",
        "refresh_expires_at",
        "user",
    }
    assert set(body["user"]) == {
        "id",
        "phone_e164",
        "display_name",
        "timezone",
        "status",
        "created_at",
        "updated_at",
    }
    assert body["access_expires_at"] == "2026-09-09T18:30:00Z"
    assert "test-only" not in repr(credentials)
    request = OtpRequestResponse(
        challenge_id=uuid4(),
        expires_at=now,
        resend_after_seconds=60,
        message="Verification requested.",
    )
    assert set(request.model_dump()) == {
        "challenge_id",
        "expires_at",
        "resend_after_seconds",
        "message",
    }
    assert (
        DeactivationResponse(status="DEACTIVATED", deactivated_at=now).deactivated_at.tzinfo == UTC
    )
    assert LogoutResponse(logged_out=True).model_dump() == {"logged_out": True}
    assert RefreshRequest(refresh_token="x" * 512).refresh_token == "x" * 512
    with pytest.raises(ValidationError):
        LogoutResponse(logged_out=False)
    with pytest.raises(ValidationError):
        OtpRequestResponse(
            challenge_id=uuid4(),
            expires_at=datetime(2026, 9, 10),
            resend_after_seconds=60,
            message="Verification requested.",
        )


def test_route_free_json_schema_contract():
    schema = TypeAdapter(OtpVerifyRequest).json_schema()
    assert len(schema["anyOf"]) == 2
    for definition in schema["$defs"].values():
        assert definition["additionalProperties"] is False
        assert "intent" not in definition["properties"]
        assert definition["properties"]["code"]["type"] == "string"
    patch = ProfileUpdateRequest.model_json_schema()
    assert patch["minProperties"] == 1
    assert "anyOf" not in patch["properties"]["display_name"]
    assert LogoutResponse.model_json_schema()["properties"]["logged_out"]["const"] is True


@pytest.mark.parametrize("value", [1, 0, "true", None, False])
def test_logout_response_requires_boolean_true(value):
    with pytest.raises(ValidationError):
        LogoutResponse(logged_out=value)


def test_only_approved_b2_routes_are_registered():
    from app.main import create_app

    assert {
        path
        for path in create_app().openapi()["paths"]
        if not path.startswith(("/api/v1/connections", "/api/v1/commitments"))
    } == {
        "/health",
        "/readiness",
        "/api/v1/auth/otp/request",
        "/api/v1/auth/otp/verify",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/me",
        "/api/v1/me/deactivate",
    }
