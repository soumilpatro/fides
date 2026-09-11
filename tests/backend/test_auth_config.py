"""Authentication configuration accepts safe local startup and fails closed for Twilio."""

import pytest
from app.config import Settings
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    import os

    for key in tuple(os.environ):
        if key.lower() in Settings.model_fields:
            monkeypatch.delenv(key)


def twilio_settings(**overrides):
    return {
        "otp_provider": "twilio",
        "twilio_api_key_sid": "SK" + "1" * 32,
        "twilio_api_key_secret": "test-only-api-secret",
        "twilio_verify_signup_service_sid": "VA" + "2" * 32,
        "twilio_verify_login_service_sid": "VA" + "3" * 32,
        "auth_rate_limit_hmac_secret": "test-only-hmac-secret",
        **overrides,
    }


def test_approved_defaults():
    settings = Settings(_env_file=None)
    expected = {
        "auth_access_token_ttl_seconds": 900,
        "auth_refresh_session_ttl_seconds": 2592000,
        "otp_code_length": 6,
        "otp_challenge_ttl_seconds": 600,
        "otp_provider_operation_lease_seconds": 30,
        "otp_resend_cooldown_seconds": 60,
        "otp_request_phone_10m_limit": 3,
        "otp_request_phone_24h_limit": 10,
        "otp_request_ip_10m_limit": 20,
        "otp_request_ip_24h_limit": 100,
        "otp_verify_challenge_limit": 5,
        "otp_verify_phone_10m_limit": 10,
        "otp_verify_ip_1m_limit": 30,
        "otp_verify_ip_1h_limit": 200,
        "auth_refresh_session_1m_limit": 10,
        "auth_refresh_ip_1m_limit": 60,
        "otp_provider_connect_timeout_seconds": 2,
        "otp_provider_read_timeout_seconds": 5,
        "otp_provider_write_timeout_seconds": 5,
        "otp_provider_pool_timeout_seconds": 1,
        "otp_provider_operation_budget_seconds": 10,
        "auth_otp_cleanup_retention_seconds": 86400,
        "auth_rate_limit_cleanup_retention_seconds": 86400,
        "auth_session_cleanup_retention_seconds": 2592000,
    }
    assert {key: getattr(settings, key) for key in expected} == expected
    assert settings.otp_provider == "disabled"


@pytest.mark.parametrize(
    "field",
    [
        name
        for name in Settings.model_fields
        if name.endswith(("_seconds", "_limit")) or name == "otp_code_length"
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_reject_non_positive_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"otp_code_length": 7},
        {"auth_access_token_ttl_seconds": 2592001},
        {"otp_provider_operation_budget_seconds": 30},
        {"otp_provider_operation_lease_seconds": 600},
        {"otp_resend_cooldown_seconds": 600},
        {"otp_provider_read_timeout_seconds": 11},
    ],
)
def test_reject_incoherent_settings(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


@pytest.mark.parametrize("field", list(twilio_settings())[1:])
def test_twilio_requires_all_configuration(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **twilio_settings(**{field: ""}))


def test_distinct_services_required_and_secrets_redacted():
    settings = Settings(_env_file=None, **twilio_settings(app_env="production"))
    assert "test-only" not in repr(settings)
    assert "test-only" not in settings.model_dump_json()
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, **twilio_settings(twilio_verify_login_service_sid="VA" + "2" * 32))
    assert "test-only" not in str(exc.value)


@pytest.mark.parametrize("provider", ["disabled", "fake"])
@pytest.mark.parametrize("environment", ["production", "staging", " production ", " STAGING "])
def test_deployed_environment_cannot_fall_back(provider, environment):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, otp_provider=provider, app_env=environment)


def test_fake_requires_no_twilio_credentials(monkeypatch):
    monkeypatch.setenv("OTP_PROVIDER", "fake")
    monkeypatch.setenv("AUTH_RATE_LIMIT_HMAC_SECRET", "test-only-hmac-secret")
    monkeypatch.setenv("OTP_REQUEST_PHONE_10M_LIMIT", "4")
    settings = Settings(_env_file=None)
    assert settings.otp_request_phone_10m_limit == 4
    assert not settings.twilio_api_key_secret.get_secret_value()


@pytest.mark.parametrize("environment", ["prod", "stagng", "", "unknown", None, 123])
def test_unknown_environment_fails_closed(environment):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env=environment)


def test_environment_normalizes_and_database_credentials_are_not_in_repr():
    settings = Settings(
        _env_file=None,
        app_env=" TEST ",
        database_url="postgresql://test:private-db-password@localhost/fides_dev",
        test_database_url="postgresql://test:private-db-password@localhost/fides_test",
    )
    assert settings.app_env == "test"
    assert "private-db-password" not in repr(settings)
