"""Shared environment configuration, including the approved B2-D2 defaults."""

from functools import lru_cache
from ipaddress import ip_network
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from environment variables.

    Field defaults intentionally mirror `.env.example` and contain no
    secrets, per AI Build Spec B0 requirement: "Create environment
    configuration with safe defaults."
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: Literal["local", "development", "test", "staging", "production"] = "local"
    app_name: str = "fides-backend"
    log_level: str = "INFO"
    port: int = 8000

    # Database (B1). No defaults containing real credentials; the values in
    # .env.example are local-only Docker Compose development values.
    database_url: str = Field(default="", repr=False)
    test_database_url: str = Field(default="", repr=False)
    database_host: str = ""
    database_port: int = 5432
    database_name: str = ""
    database_user: str = ""
    database_password: SecretStr = Field(default=SecretStr(""), repr=False)
    database_isolation_level: Literal["READ COMMITTED"] = "READ COMMITTED"

    # Disabled is explicit and safe during foundation-only local startup.
    # No provider is constructed here; future orchestration selects an adapter.
    otp_provider: Literal["disabled", "fake", "twilio"] = "disabled"
    auth_access_token_ttl_seconds: PositiveInt = 900
    auth_refresh_session_ttl_seconds: PositiveInt = 2592000
    otp_code_length: int = Field(default=6, ge=6, le=6)
    otp_challenge_ttl_seconds: PositiveInt = 600
    otp_provider_operation_lease_seconds: PositiveInt = 30
    otp_resend_cooldown_seconds: PositiveInt = 60
    otp_request_phone_10m_limit: PositiveInt = 3
    otp_request_phone_24h_limit: PositiveInt = 10
    otp_request_ip_10m_limit: PositiveInt = 20
    otp_request_ip_24h_limit: PositiveInt = 100
    otp_verify_challenge_limit: PositiveInt = 5
    otp_verify_phone_10m_limit: PositiveInt = 10
    otp_verify_ip_1m_limit: PositiveInt = 30
    otp_verify_ip_1h_limit: PositiveInt = 200
    auth_refresh_session_1m_limit: PositiveInt = 10
    auth_refresh_ip_1m_limit: PositiveInt = 60
    auth_trusted_proxy_cidrs: tuple[str, ...] = ()

    @field_validator("auth_trusted_proxy_cidrs")
    @classmethod
    def validate_proxy_networks(cls, values):
        try:
            for value in values:
                ip_network(value, strict=True)
        except ValueError:
            raise ValueError("Trusted proxies require valid, strict CIDR networks.") from None
        return values

    twilio_api_key_sid: str = Field(default="", repr=False)
    twilio_api_key_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    twilio_verify_signup_service_sid: str = ""
    twilio_verify_login_service_sid: str = ""
    auth_rate_limit_hmac_secret: SecretStr = Field(default=SecretStr(""), repr=False)
    otp_provider_connect_timeout_seconds: PositiveFloat = 2
    otp_provider_read_timeout_seconds: PositiveFloat = 5
    otp_provider_write_timeout_seconds: PositiveFloat = 5
    otp_provider_pool_timeout_seconds: PositiveFloat = 1
    otp_provider_operation_budget_seconds: PositiveFloat = 10
    auth_otp_cleanup_retention_seconds: PositiveInt = 86400
    auth_rate_limit_cleanup_retention_seconds: PositiveInt = 86400
    auth_session_cleanup_retention_seconds: PositiveInt = 2592000

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_environment(cls, value: object) -> object:
        # Validate the normalized deployment mode before any provider safety checks.
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        database_components = (
            self.database_host,
            self.database_name,
            self.database_user,
            self.database_password.get_secret_value(),
        )
        if any(database_components) and not all(value.strip() for value in database_components):
            raise ValueError(
                "Component database configuration requires host, name, user, and password."
            )
        if self.auth_access_token_ttl_seconds > self.auth_refresh_session_ttl_seconds:
            raise ValueError("Access lifetime must not exceed the refresh-session lifetime.")
        if not (
            self.otp_provider_operation_budget_seconds
            < self.otp_provider_operation_lease_seconds
            < self.otp_challenge_ttl_seconds
        ):
            raise ValueError("Provider budget must be shorter than lease and challenge validity.")
        if self.otp_resend_cooldown_seconds >= self.otp_challenge_ttl_seconds:
            raise ValueError("Resend cooldown must be shorter than challenge validity.")
        timeouts = (
            self.otp_provider_connect_timeout_seconds,
            self.otp_provider_read_timeout_seconds,
            self.otp_provider_write_timeout_seconds,
            self.otp_provider_pool_timeout_seconds,
        )
        if max(timeouts) > self.otp_provider_operation_budget_seconds:
            raise ValueError("Network timeouts must not exceed the overall provider budget.")
        if self.app_env in {"production", "staging"} and self.otp_provider != "twilio":
            raise ValueError("Production/staging authentication requires the Twilio provider.")
        if self.otp_provider == "twilio":
            import re

            if not re.fullmatch(r"SK[0-9a-fA-F]{32}", self.twilio_api_key_sid):
                raise ValueError("Twilio requires a valid API Key SID.")
            services = (
                self.twilio_verify_signup_service_sid,
                self.twilio_verify_login_service_sid,
            )
            if any(not re.fullmatch(r"VA[0-9a-fA-F]{32}", sid) for sid in services):
                raise ValueError("Twilio requires both valid Verify Service SIDs.")
            if self.app_env == "production" and services[0] == services[1]:
                raise ValueError("Production signup and login must use distinct Verify Services.")
            if not self.twilio_api_key_secret.get_secret_value().strip():
                raise ValueError("Twilio requires an API Key Secret.")
        if self.otp_provider != "disabled":
            if not self.auth_rate_limit_hmac_secret.get_secret_value().strip():
                raise ValueError("An enabled OTP provider requires a rate-limit HMAC secret.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Cached via lru_cache so settings are parsed once per process, while
    remaining easily overridable in tests via dependency overrides or by
    calling `get_settings.cache_clear()`.
    """
    return Settings()
