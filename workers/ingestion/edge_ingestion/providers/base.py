"""Provider-agnostic contract between external data sources and the core domain.

Concrete providers translate their own payloads into these DTOs. Nothing
outside ``edge_ingestion.providers`` may depend on a provider's raw format.
Rules every implementation must follow:
- all datetimes are timezone-aware UTC
- ``provider_id`` values are stable across calls (they form idempotency keys)
- odds are decimal odds > 1.0
- network calls use timeouts/retries and never log credentials
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class TeamData:
    provider_id: str
    name: str
    short_name: str


@dataclass(frozen=True, slots=True)
class FixtureData:
    provider_id: str
    season: str
    round: int | None
    kickoff_at: datetime
    home_team_provider_id: str
    away_team_provider_id: str
    status: str  # one of edge_api.db.models.FixtureStatus values
    home_score: int | None = None
    away_score: int | None = None


@dataclass(frozen=True, slots=True)
class OddsData:
    fixture_provider_id: str
    bookmaker: str
    odds_home: float
    odds_draw: float
    odds_away: float
    captured_at: datetime
    market: str = "1X2"
    raw: dict[str, Any] = field(default_factory=dict)


class FootballDataProvider(ABC):
    name: str
    league: str = "EPL"

    @abstractmethod
    def get_teams(self) -> list[TeamData]: ...

    @abstractmethod
    def get_fixtures(self, date_from: datetime, date_to: datetime) -> list[FixtureData]:
        """Fixtures with kickoff in [date_from, date_to)."""

    @abstractmethod
    def get_odds(self, fixture_provider_ids: Sequence[str]) -> list[OddsData]:
        """All odds snapshots the provider has captured so far for these fixtures."""
