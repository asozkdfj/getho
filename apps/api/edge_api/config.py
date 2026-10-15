from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Default market-baseline bookmaker per data provider (slugs as stored in odds_snapshots).
DEFAULT_BOOKMAKERS = {"mock": "mockbook", "api_football": "bet365"}
# API-Football refreshes odds ~every 3h; the mock captures at 10d/48h/6h before kickoff.
DEFAULT_ODDS_MAX_AGE_HOURS = {"mock": 72.0, "api_football": 12.0}


class Settings(BaseSettings):
    """Runtime configuration. Secrets are SecretStr so they never appear in reprs/logs."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: SecretStr = SecretStr("postgresql+psycopg://edge:edge@localhost:5432/edge")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    data_provider: str = "mock"  # mock | api_football
    # Bookmaker whose prices are the market baseline. Empty -> provider default.
    primary_bookmaker: str | None = None

    # --- API-Football (api-sports.io v3); only used when data_provider=api_football
    api_football_key: SecretStr | None = None
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_football_league_id: int = 39  # Premier League
    api_football_season: int | None = None  # start year, e.g. 2026; None -> derived
    api_football_bookmaker_id: int | None = None  # None -> all bookmakers
    # Free plan allows ~10 requests/minute -> 6.5s spacing. Lower it on paid plans.
    api_football_min_interval_seconds: float = 6.5
    api_football_timeout_seconds: float = 15.0

    git_sha: str | None = None

    # comma-separated in the environment (NoDecode: not parsed as JSON)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    value_threshold: float = 0.03

    # --- Today's Pick (thresholds come from the backtest, see docs/MODEL_EVALUATION.md)
    pick_min_probability: float = 0.55
    pick_tz: str = "Asia/Seoul"
    pick_publish_hour: int = 9  # local hour (pick_tz) when the day's pick is decided
    pick_replace_on_void: bool = False  # publish a new pick if the chosen match is voided

    # --- data quality gates
    odds_max_age_hours: float | None = None  # None -> provider default
    ingest_max_age_hours: float = 8.0
    min_team_matches: int = 10

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("data_provider", mode="before")
    @classmethod
    def _normalise_provider(cls, v: object) -> object:
        # "API-Football" / "api-football" -> "api_football" (one canonical name everywhere,
        # because it is also stored in fixtures.provider and used to scope queries)
        return v.strip().lower().replace("-", "_") if isinstance(v, str) else v

    @field_validator(
        "api_football_key",
        "primary_bookmaker",
        "api_football_season",
        "api_football_bookmaker_id",
        "odds_max_age_hours",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if v == "" else v

    @property
    def odds_max_age(self) -> float:
        return self.odds_max_age_hours or DEFAULT_ODDS_MAX_AGE_HOURS.get(self.data_provider, 12.0)

    @property
    def bookmaker(self) -> str:
        """Resolved market-baseline bookmaker (normalised slug, e.g. "bet365")."""
        return self.primary_bookmaker or DEFAULT_BOOKMAKERS.get(self.data_provider, "mockbook")


@lru_cache
def get_settings() -> Settings:
    return Settings()
