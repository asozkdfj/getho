from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets are SecretStr so they never appear in reprs/logs."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: SecretStr = SecretStr("postgresql+psycopg://edge:edge@localhost:5432/edge")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    data_provider: str = "mock"
    primary_bookmaker: str = "mockbook"
    football_data_api_key: SecretStr | None = None

    git_sha: str | None = None

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    value_threshold: float = 0.03

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("football_data_api_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, v: object) -> object:
        return None if v == "" else v


@lru_cache
def get_settings() -> Settings:
    return Settings()
