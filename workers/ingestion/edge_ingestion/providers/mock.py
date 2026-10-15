"""Deterministic mock EPL provider - no network, no API key.

Synthetic data only: team names are used as labels, but results, odds and
strengths are generated and do NOT reflect real matches.

Determinism: the schedule is anchored on a fixed 4-day grid, and every score
or price comes from an RNG seeded by a stable hash of the fixture id. Re-running
ingestion within the same grid window therefore produces byte-identical data,
which is what makes the seed idempotent. When the window moves (every 4 days)
the mock "reschedules" the season around the new date: fixture rows are upserted
(kickoff/status change) and new odds snapshots are appended.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import numpy as np

from edge_ingestion.providers.base import FixtureData, FootballDataProvider, OddsData, TeamData
from edge_ml.poisson import probabilities_from_expected_goals


@dataclass(frozen=True, slots=True)
class _MockTeam:
    code: str
    name: str
    short_name: str
    attack: float  # hidden "true" strengths used to simulate results/odds
    defence: float


TEAMS: tuple[_MockTeam, ...] = (
    _MockTeam("ARS", "Arsenal", "ARS", 1.45, 0.70),
    _MockTeam("AVL", "Aston Villa", "AVL", 1.15, 0.95),
    _MockTeam("BOU", "Bournemouth", "BOU", 1.00, 1.05),
    _MockTeam("BRE", "Brentford", "BRE", 1.00, 1.10),
    _MockTeam("BHA", "Brighton & Hove Albion", "BHA", 1.05, 1.00),
    _MockTeam("BUR", "Burnley", "BUR", 0.75, 1.30),
    _MockTeam("CHE", "Chelsea", "CHE", 1.30, 0.85),
    _MockTeam("CRY", "Crystal Palace", "CRY", 0.95, 0.95),
    _MockTeam("EVE", "Everton", "EVE", 0.85, 1.00),
    _MockTeam("FUL", "Fulham", "FUL", 0.95, 1.05),
    _MockTeam("LEE", "Leeds United", "LEE", 0.85, 1.20),
    _MockTeam("LIV", "Liverpool", "LIV", 1.50, 0.80),
    _MockTeam("MCI", "Manchester City", "MCI", 1.45, 0.80),
    _MockTeam("MUN", "Manchester United", "MUN", 1.05, 1.05),
    _MockTeam("NEW", "Newcastle United", "NEW", 1.20, 0.90),
    _MockTeam("NFO", "Nottingham Forest", "NFO", 0.95, 1.00),
    _MockTeam("SUN", "Sunderland", "SUN", 0.80, 1.20),
    _MockTeam("TOT", "Tottenham Hotspur", "TOT", 1.15, 1.05),
    _MockTeam("WHU", "West Ham United", "WHU", 0.90, 1.20),
    _MockTeam("WOL", "Wolverhampton Wanderers", "WOL", 0.80, 1.25),
)

MU_HOME = 1.55
MU_AWAY = 1.25
BOOKMAKER = "mockbook"
BOOK_MARGIN = 0.05
GRID_EPOCH = datetime(2020, 1, 1, tzinfo=UTC)
ROUND_SPACING = timedelta(days=4)
CURRENT_ROUND_INDEX = 12  # 0-based index of the round containing "now"
SEASON_BREAK_ROUNDS = 10  # ~40 day gap between the previous and current season
MATCH_DURATION = timedelta(hours=2)
KICKOFF_SLOTS = (time(12, 30), time(15, 0), time(19, 0))
# Odds snapshots are "captured" at these offsets before kickoff.
SNAPSHOT_OFFSETS = (timedelta(days=10), timedelta(hours=48), timedelta(hours=6))


def _seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _round_robin(codes: Sequence[str]) -> list[list[tuple[str, str]]]:
    """Circle-method double round robin: 2*(n-1) rounds of n/2 matches."""
    teams = list(codes)
    n = len(teams)
    first_half: list[list[tuple[str, str]]] = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        first_half.append(pairs)
        teams = [teams[0], teams[-1], *teams[1:-1]]
    second_half = [[(b, a) for a, b in rnd] for rnd in first_half]
    return first_half + second_half


def _season_label(d: datetime) -> str:
    start_year = d.year if d.month >= 7 else d.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


class MockProvider(FootballDataProvider):
    name = "mock"

    def __init__(self, reference_time: datetime | None = None) -> None:
        ref = reference_time or datetime.now(UTC)
        if ref.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")
        self.reference_time = ref.astimezone(UTC)
        grid_index = (self.reference_time - GRID_EPOCH) // ROUND_SPACING
        current_round_start = GRID_EPOCH + grid_index * ROUND_SPACING
        self.season_start = current_round_start - CURRENT_ROUND_INDEX * ROUND_SPACING
        self.season = _season_label(current_round_start)
        self._teams = {t.code: t for t in TEAMS}
        self._fixtures = self._build_fixtures()
        self._by_id = {f.provider_id: f for f in self._fixtures}

    # ------------------------------------------------------------------ teams
    def get_teams(self) -> list[TeamData]:
        return [TeamData(t.code, t.name, t.short_name) for t in TEAMS]

    # --------------------------------------------------------------- fixtures
    def _expected_goals(self, home: str, away: str) -> tuple[float, float]:
        h, a = self._teams[home], self._teams[away]
        return MU_HOME * h.attack * a.defence, MU_AWAY * a.attack * h.defence

    def _build_fixtures(self) -> list[FixtureData]:
        """Current season plus the previous one (history for rating fits)."""
        start_year = int(self.season[:4])
        prev_season = f"{start_year - 1}-{start_year % 100:02d}"
        rounds = _round_robin([t.code for t in TEAMS])
        prev_start = self.season_start - (len(rounds) + SEASON_BREAK_ROUNDS) * ROUND_SPACING
        out: list[FixtureData] = []
        for season, start in ((prev_season, prev_start), (self.season, self.season_start)):
            for r_idx, pairs in enumerate(rounds):
                round_start = start + r_idx * ROUND_SPACING
                for j, (home, away) in enumerate(pairs):
                    day = round_start + timedelta(days=j % 4)
                    kickoff = datetime.combine(day.date(), KICKOFF_SLOTS[j // 4], tzinfo=UTC)
                    pid = f"{season}-r{r_idx + 1:02d}-{home}-{away}"
                    status, hs, as_ = self._status_and_score(pid, home, away, kickoff)
                    out.append(
                        FixtureData(
                            provider_id=pid,
                            season=season,
                            round=r_idx + 1,
                            kickoff_at=kickoff,
                            home_team_provider_id=home,
                            away_team_provider_id=away,
                            status=status,
                            home_score=hs,
                            away_score=as_,
                        )
                    )
        return out

    def _status_and_score(
        self, pid: str, home: str, away: str, kickoff: datetime
    ) -> tuple[str, int | None, int | None]:
        if self.reference_time >= kickoff + MATCH_DURATION:
            rng = np.random.default_rng(_seed("score", pid))
            lam_h, lam_a = self._expected_goals(home, away)
            return "finished", int(rng.poisson(lam_h)), int(rng.poisson(lam_a))
        if self.reference_time >= kickoff:
            return "live", None, None
        return "scheduled", None, None

    def get_fixtures(self, date_from: datetime, date_to: datetime) -> list[FixtureData]:
        return [f for f in self._fixtures if date_from <= f.kickoff_at < date_to]

    # ------------------------------------------------------------------- odds
    def get_odds(self, fixture_provider_ids: Sequence[str]) -> list[OddsData]:
        out: list[OddsData] = []
        for pid in fixture_provider_ids:
            fixture = self._by_id.get(pid)
            if fixture is None:
                continue
            for k, offset in enumerate(SNAPSHOT_OFFSETS):
                captured = fixture.kickoff_at - offset
                if captured > self.reference_time:
                    continue  # cannot capture the future
                out.append(self._price(fixture, k, captured))
        return out

    def _price(self, fixture: FixtureData, k: int, captured: datetime) -> OddsData:
        rng = np.random.default_rng(_seed("odds", fixture.provider_id, k))
        lam_h, lam_a = self._expected_goals(
            fixture.home_team_provider_id, fixture.away_team_provider_id
        )
        # market opinion = truth + noise (the market is good but not perfect)
        lam_h *= float(np.exp(rng.normal(0, 0.08)))
        lam_a *= float(np.exp(rng.normal(0, 0.08)))
        probs = probabilities_from_expected_goals(lam_h, lam_a).as_tuple()
        odds = [max(round(1.0 / (p * (1 + BOOK_MARGIN)), 2), 1.01) for p in probs]
        return OddsData(
            fixture_provider_id=fixture.provider_id,
            bookmaker=BOOKMAKER,
            odds_home=odds[0],
            odds_draw=odds[1],
            odds_away=odds[2],
            captured_at=captured,
            raw={"source": "mock", "snapshot_index": k, "margin": BOOK_MARGIN},
        )
