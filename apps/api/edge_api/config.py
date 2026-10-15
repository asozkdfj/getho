from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Default market-baseline bookmaker per data provider (slugs as stored in odds_snapshots).
DEFAULT_BOOKMAKERS = {"mock": "mockbook", "api_football": "bet365"}
# API-Football refreshes odds ~every 3h; the mock captures at 10d/48h/6h before kickoff.
DEFAULT_ODDS_MAX_AGE_HOURS = {"mock": 72.0, "api_football": 12.0}
# Fetching odds for every league costs ~1 request per 10 fixtures, so the real
# provider only looks a few days ahead (prices appear ~1-14 days before kickoff).
DEFAULT_ODDS_LOOKAHEAD_DAYS = {"mock": 14, "api_football": 3}


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
    # "all" = every league of the plan's catalogue; or comma-separated ids ("39,140")
    api_football_leagues: str = "all"
    api_football_bookmaker_id: int | None = None  # None -> all bookmakers
    # Spacing before the first response; afterwards the plan's per-minute limit
    # (response header) sets the pace (free 10/min, pro 300/min).
    api_football_min_interval_seconds: float = 6.5
    api_football_timeout_seconds: float = 15.0
    # Stop optional work (history backfill, extra odds pages) below this many
    # requests left today, so the day's essential refreshes still fit.
    api_football_min_remaining: int = 300

    # --- multi-league ingestion
    # Leagues whose past results are fetched per run (2 requests each) until all
    # leagues with upcoming fixtures have history.
    backfill_leagues_per_run: int = 40
    # Odds are fetched for fixtures kicking off within this many days.
    odds_lookahead_days: int | None = None  # None -> provider default

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
    # Leagues the pick may come from: "verified" (accuracy measured by the backtest),
    # "all" (every predicted league) or comma-separated provider league ids.
    pick_leagues: str = "verified"

    # --- team news (absences days before, official line-ups ~1h before kickoff)
    # Leagues to collect for: "verified", "all" or comma-separated provider league ids.
    team_news_leagues: str = "verified"
    lineup_window_minutes: int = 90  # look for line-ups of matches starting this soon
    absences_horizon_hours: int = 48
    appearances_per_run: int = 200  # finished fixtures whose player minutes are fetched

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
        "api_football_bookmaker_id",
        "odds_lookahead_days",
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
    def odds_lookahead(self) -> int:
        return self.odds_lookahead_days or DEFAULT_ODDS_LOOKAHEAD_DAYS.get(self.data_provider, 3)

    @property
    def bookmaker(self) -> str:
        """Resolved market-baseline bookmaker (normalised slug, e.g. "bet365")."""
        return self.primary_bookmaker or DEFAULT_BOOKMAKERS.get(self.data_provider, "mockbook")


@lru_cache
def get_settings() -> Settings:
    return Settings()
