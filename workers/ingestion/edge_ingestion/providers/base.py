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
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

LEAGUE_TYPES = ("league", "cup")


@dataclass(frozen=True, slots=True)
class LeagueData:
    provider_id: str
    name: str
    country: str
    type: str  # "league" (round robin table) | "cup" (knockout / mixed)
    season: str | None  # label of the current season, e.g. "2026-27" or "2026"
    season_year: int | None = None  # provider's key for the current season
    country_code: str | None = None
    has_odds: bool = False
    has_injuries: bool = False  # the provider reports injuries/suspensions for it
    logo_url: str | None = None
    flag_url: str | None = None


@dataclass(frozen=True, slots=True)
class TeamData:
    provider_id: str
    name: str
    short_name: str
    logo_url: str | None = None


@dataclass(frozen=True, slots=True)
class FixtureData:
    provider_id: str
    league_provider_id: str
    season: str
    round: int | None
    kickoff_at: datetime
    home_team: TeamData
    away_team: TeamData
    status: str  # one of edge_api.db.models.FixtureStatus values
    home_score: int | None = None
    away_score: int | None = None

    @property
    def home_team_provider_id(self) -> str:
        return self.home_team.provider_id

    @property
    def away_team_provider_id(self) -> str:
        return self.away_team.provider_id


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


@dataclass(frozen=True, slots=True)
class PlayerRef:
    provider_id: str
    name: str
    number: int | None = None
    position: str | None = None  # G / D / M / F when known


@dataclass(frozen=True, slots=True)
class LineupData:
    """Official starting XI of one team (published shortly before kickoff)."""

    fixture_provider_id: str
    team_provider_id: str
    formation: str | None
    starters: tuple[PlayerRef, ...]
    substitutes: tuple[PlayerRef, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchStatistics:
    """One team's post-match statistics. ``expected_goals`` is the provider's
    xG when it publishes one for the league, else None (never a guess)."""

    fixture_provider_id: str
    team_provider_id: str
    shots: int | None
    shots_on_target: int | None
    expected_goals: float | None


@dataclass(frozen=True, slots=True)
class PostMatchReport:
    """What a finished fixture's details tell: player minutes and team statistics."""

    appearances: list[AppearanceData]
    statistics: list[MatchStatistics]


@dataclass(frozen=True, slots=True)
class AbsenceReport:
    """Absences plus the fixtures the provider actually answered for. A covered
    fixture with no absence for a team means "checked, none reported"; a
    fixture outside ``covered`` means "not checked" (unknown), never "none"."""

    absences: list[AbsenceData]
    covered: frozenset[str]


@dataclass(frozen=True, slots=True)
class AbsenceData:
    """A player reported unavailable or doubtful for a fixture."""

    fixture_provider_id: str
    team_provider_id: str
    player: PlayerRef
    status: str  # "out" | "doubtful"
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AppearanceData:
    """Minutes one player played in a finished fixture."""

    fixture_provider_id: str
    team_provider_id: str
    player: PlayerRef
    started: bool
    minutes: int


class FootballDataProvider(ABC):
    """One data source covering any number of leagues.

    Ingestion calls, per run: ``get_leagues`` (catalogue), ``get_fixtures`` for a
    short rolling window around now (all leagues), ``get_league_history`` for
    leagues whose past results are not in the database yet, and ``get_odds`` for
    upcoming fixtures.
    """

    name: str

    @abstractmethod
    def get_leagues(self) -> list[LeagueData]:
        """Competitions this provider serves (already filtered by configuration)."""

    @abstractmethod
    def get_fixtures(self, date_from: datetime, date_to: datetime) -> list[FixtureData]:
        """Fixtures of every served league with kickoff in [date_from, date_to)."""

    @abstractmethod
    def get_league_history(self, league: LeagueData) -> list[FixtureData]:
        """Current and previous season of one league (results for rating fits)."""

    @abstractmethod
    def get_odds(self, fixtures: Mapping[str, datetime]) -> list[OddsData]:
        """Odds captured so far for these fixtures (provider_id -> kickoff time)."""

    def get_season_fixtures(self, league_provider_id: str, year: int) -> list[FixtureData]:
        """Every fixture of one league season, e.g. for research exports of past
        seasons (optional; providers without it return nothing)."""
        return []

    def get_fixtures_by_ids(self, fixture_provider_ids: list[str]) -> list[FixtureData]:
        """Current state of specific fixtures, e.g. ones the rolling date window no
        longer returns because they were moved to another day (optional)."""
        return []

    # ---- team news (optional: providers without it simply return nothing)
    def get_absences(self, fixtures: Mapping[str, datetime]) -> list[AbsenceData]:
        """Injured / suspended / doubtful players for these upcoming fixtures."""
        return []

    def get_absence_report(self, fixtures: Mapping[str, datetime]) -> AbsenceReport:
        """Absences and the fixtures they cover. The default claims no coverage,
        so a provider that cannot say what it checked never yields "none"."""
        return AbsenceReport(self.get_absences(fixtures), frozenset())

    def get_lineups(self, fixture_provider_ids: list[str]) -> list[LineupData]:
        """Official line-ups already published for these fixtures."""
        return []

    def get_match_statistics(self, fixture_provider_ids: list[str]) -> list[MatchStatistics]:
        """Post-match team statistics (shots, shots on target, xG when provided)."""
        return []

    def get_post_match(self, fixture_provider_ids: list[str]) -> PostMatchReport:
        """Player minutes and team statistics together. Providers that read both
        from one response override this so the details are fetched once."""
        return PostMatchReport(
            self.get_appearances(fixture_provider_ids),
            self.get_match_statistics(fixture_provider_ids),
        )

    def get_appearances(self, fixture_provider_ids: list[str]) -> list[AppearanceData]:
        """Player minutes of these finished fixtures."""
        return []

    def budget_ok(self) -> bool:
        """False when optional work (history backfill) should wait for a later run."""
        return True

    @property
    def requests_made(self) -> int:
        return 0
