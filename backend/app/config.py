"""Environment/configuration loading for the FIDES backend (B0 scope).

Only generic service configuration is defined here. Database, auth, and
domain-specific configuration are out of scope for B0 and will be added
starting B1 (database infrastructure) and B2 (identity & authentication)
per the AI Development & Backend Build Specification build order.

Settings are loaded from environment variables (and an optional local
`.env` file for development). No default value here is a secret; see
`.env.example` for the documented set of variables.
"""

from functools import lru_cache

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
    )

    app_env: str = "local"
    app_name: str = "fides-backend"
    log_level: str = "INFO"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Cached via lru_cache so settings are parsed once per process, while
    remaining easily overridable in tests via dependency overrides or by
    calling `get_settings.cache_clear()`.
    """
    return Settings()
