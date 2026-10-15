from __future__ import annotations

from datetime import datetime

from edge_api.config import Settings, get_settings
from edge_ingestion.providers.api_football import ApiFootballProvider
from edge_ingestion.providers.base import FootballDataProvider
from edge_ingestion.providers.mock import MockProvider

AVAILABLE = ("mock", "api_football")


def get_provider(
    name: str, *, settings: Settings | None = None, reference_time: datetime | None = None
) -> FootballDataProvider:
    """Build the configured provider. Secrets come from Settings, never from code."""
    settings = settings or get_settings()
    if name == "mock":
        return MockProvider(reference_time=reference_time)
    if name == "api_football":
        if settings.api_football_key is None:
            raise ValueError("DATA_PROVIDER=api_football requires API_FOOTBALL_KEY")
        return ApiFootballProvider(
            settings.api_football_key.get_secret_value(),
            reference_time=reference_time,
            base_url=settings.api_football_base_url,
            league_id=settings.api_football_league_id,
            season=settings.api_football_season,
            bookmaker_id=settings.api_football_bookmaker_id,
            min_interval_seconds=settings.api_football_min_interval_seconds,
            timeout_seconds=settings.api_football_timeout_seconds,
        )
    raise ValueError(f"unknown data provider: {name!r} (available: {', '.join(AVAILABLE)})")


__all__ = [
    "AVAILABLE",
    "ApiFootballProvider",
    "FootballDataProvider",
    "MockProvider",
    "get_provider",
]
