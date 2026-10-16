"""Deterministic mock provider - no network, no API key.

Several synthetic competitions (Premier League, La Liga, K League 1 and the
FA Cup as an example of a cup) so the multi-league catalogue, categorisation
and per-league models can be exercised offline. Team names are used as labels
only: results, odds and strengths are generated and do NOT reflect real matches.

Determinism: the schedule is anchored on a fixed 4-day grid, and every score
or price comes from an RNG seeded by a stable hash of the fixture id. Re-running
ingestion within the same grid window therefore produces byte-identical data,
which is what makes the seed idempotent. When the window moves (every 4 days)
the mock "reschedules" the season around the new date: fixture rows are upserted
(kickoff/status change) and new odds snapshots are appended.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import numpy as np

from edge_ingestion.providers.base import (
    AbsenceData,
    AppearanceData,
    FixtureData,
    FootballDataProvider,
    LeagueData,
    LineupData,
    OddsData,
    PlayerRef,
    TeamData,
)
from edge_ml.poisson import probabilities_from_expected_goals


@dataclass(frozen=True, slots=True)
class _MockTeam:
    code: str
    name: str
    short_name: str
    attack: float  # hidden "true" strengths used to simulate results/odds
    defence: float


EPL_TEAMS: tuple[_MockTeam, ...] = (
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

LALIGA_TEAMS: tuple[_MockTeam, ...] = (
    _MockTeam("RMA", "Real Madrid", "RMA", 1.50, 0.75),
    _MockTeam("FCB", "Barcelona", "BAR", 1.50, 0.80),
    _MockTeam("ATM", "Atletico Madrid", "ATM", 1.25, 0.75),
    _MockTeam("ATH", "Athletic Club", "ATH", 1.10, 0.90),
    _MockTeam("RSO", "Real Sociedad", "RSO", 1.00, 0.95),
    _MockTeam("VIL", "Villarreal", "VIL", 1.15, 1.00),
    _MockTeam("BET", "Real Betis", "BET", 1.05, 1.00),
    _MockTeam("SEV", "Sevilla", "SEV", 0.95, 1.05),
    _MockTeam("VAL", "Valencia", "VAL", 0.90, 1.05),
    _MockTeam("GIR", "Girona", "GIR", 1.05, 1.10),
    _MockTeam("CEL", "Celta Vigo", "CEL", 0.95, 1.10),
    _MockTeam("OSA", "Osasuna", "OSA", 0.90, 1.00),
    _MockTeam("GET", "Getafe", "GET", 0.80, 0.95),
    _MockTeam("MLL", "Mallorca", "MLL", 0.85, 1.05),
    _MockTeam("RAY", "Rayo Vallecano", "RAY", 0.90, 1.05),
    _MockTeam("ESP", "Espanyol", "ESP", 0.85, 1.10),
    _MockTeam("ALA", "Alaves", "ALA", 0.85, 1.10),
    _MockTeam("LEV", "Levante", "LEV", 0.85, 1.20),
    _MockTeam("ELC", "Elche", "ELC", 0.80, 1.20),
    _MockTeam("OVI", "Real Oviedo", "OVI", 0.75, 1.20),
)

KLEAGUE_TEAMS: tuple[_MockTeam, ...] = (
    _MockTeam("ULS", "Ulsan HD", "ULS", 1.30, 0.85),
    _MockTeam("JBK", "Jeonbuk Hyundai Motors", "JBK", 1.35, 0.80),
    _MockTeam("POH", "Pohang Steelers", "POH", 1.10, 0.95),
    _MockTeam("SEO", "FC Seoul", "SEO", 1.10, 0.95),
    _MockTeam("GWJ", "Gwangju FC", "GWJ", 1.00, 1.00),
    _MockTeam("GAN", "Gangwon FC", "GAN", 1.05, 1.00),
    _MockTeam("DJN", "Daejeon Hana Citizen", "DJN", 1.05, 1.00),
    _MockTeam("GIM", "Gimcheon Sangmu", "GIM", 1.10, 0.95),
    _MockTeam("SUW", "Suwon FC", "SUW", 0.95, 1.10),
    _MockTeam("JEJ", "Jeju SK", "JEJ", 0.90, 1.05),
    _MockTeam("ANY", "FC Anyang", "ANY", 0.90, 1.10),
    _MockTeam("DGU", "Daegu FC", "DGU", 0.85, 1.15),
)


@dataclass(frozen=True, slots=True)
class _MockLeague:
    provider_id: str
    name: str
    country: str
    country_code: str
    type: str
    teams: tuple[_MockTeam, ...]
    kickoff_slots: tuple[time, ...]
    day_offset: int  # shifts the grid so leagues do not all play on the same days
    id_prefix: str  # "" for the Premier League keeps fixture ids of earlier versions
    calendar_year: bool = False  # "2026" instead of "2026-27"
    mu_home: float = 1.55
    mu_away: float = 1.25


# EPL fixture ids keep the pre-multi-league format ("2026-27-r01-ARS-CHE").
LEAGUES: tuple[_MockLeague, ...] = (
    _MockLeague(
        "eng-1",
        "Premier League",
        "England",
        "GB-ENG",
        "league",
        EPL_TEAMS,
        (time(12, 30), time(15, 0), time(19, 0)),
        0,
        "",
    ),
    _MockLeague(
        "esp-1",
        "La Liga",
        "Spain",
        "ES",
        "league",
        LALIGA_TEAMS,
        (time(14, 0), time(16, 15), time(19, 0)),
        1,
        "esp-1-",
        mu_home=1.50,
        mu_away=1.15,
    ),
    _MockLeague(
        "kor-1",
        "K League 1",
        "South Korea",
        "KR",
        "league",
        KLEAGUE_TEAMS,
        (time(5, 0), time(7, 30), time(10, 0)),  # 14:00 / 16:30 / 19:00 KST
        2,
        "kor-1-",
        calendar_year=True,
        mu_home=1.40,
        mu_away=1.10,
    ),
    _MockLeague(
        "eng-cup",
        "FA Cup",
        "England",
        "GB-ENG",
        "cup",
        EPL_TEAMS,
        (time(17, 30),),
        3,
        "eng-cup-",
    ),
)
CUP_ROUND_SPACING = timedelta(days=12)
CUP_TIES_PER_ROUND = 4

BOOKMAKER = "mockbook"
BOOK_MARGIN = 0.05
GRID_EPOCH = datetime(2020, 1, 1, tzinfo=UTC)
ROUND_SPACING = timedelta(days=4)
CURRENT_ROUND_INDEX = 12  # 0-based index of the round containing "now"
SEASON_BREAK_ROUNDS = 10  # ~40 day gap between the previous and current season
MATCH_DURATION = timedelta(hours=2)
KICKOFF_SLOTS = (time(12, 30), time(15, 0), time(19, 0))
# Team news: absences are known 2 days before kickoff, line-ups 60 minutes before.
ABSENCES_KNOWN = timedelta(days=2)
LINEUPS_KNOWN = timedelta(minutes=60)
SQUAD_POSITIONS = "GDDDDMMMFFF" + "GDDMMFF"  # 11 usual starters + 7 squad players
P_OUT, P_DOUBTFUL = 0.08, 0.05
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


def _season_start_year(d: datetime, calendar_year: bool) -> int:
    if calendar_year:
        return d.year
    return d.year if d.month >= 7 else d.year - 1


def _season_label(start_year: int, calendar_year: bool) -> str:
    return str(start_year) if calendar_year else f"{start_year}-{(start_year + 1) % 100:02d}"


class MockProvider(FootballDataProvider):
    name = "mock"

    def __init__(self, reference_time: datetime | None = None) -> None:
        ref = reference_time or datetime.now(UTC)
        if ref.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")
        self.reference_time = ref.astimezone(UTC)
        grid_index = (self.reference_time - GRID_EPOCH) // ROUND_SPACING
        self.current_round_start = GRID_EPOCH + grid_index * ROUND_SPACING
        self.season_start = self.current_round_start - CURRENT_ROUND_INDEX * ROUND_SPACING
        self._teams = {t.code: t for lg in LEAGUES for t in lg.teams}
        self._leagues = {lg.provider_id: lg for lg in LEAGUES}
        self._fixtures: dict[str, list[FixtureData]] = {
            lg.provider_id: self._build_fixtures(lg) for lg in LEAGUES
        }
        self._by_id = {f.provider_id: f for fs in self._fixtures.values() for f in fs}

    @property
    def season(self) -> str:
        """Current Premier League season label (kept for callers of earlier versions)."""
        return _season_label(_season_start_year(self.current_round_start, False), False)

    # ---------------------------------------------------------------- leagues
    def get_leagues(self) -> list[LeagueData]:
        out = []
        for lg in LEAGUES:
            year = _season_start_year(self.current_round_start, lg.calendar_year)
            out.append(
                LeagueData(
                    provider_id=lg.provider_id,
                    name=lg.name,
                    country=lg.country,
                    country_code=lg.country_code,
                    type=lg.type,
                    season=_season_label(year, lg.calendar_year),
                    season_year=year,
                    has_odds=True,
                )
            )
        return out

    # --------------------------------------------------------------- fixtures
    def _team(self, code: str) -> TeamData:
        t = self._teams[code]
        return TeamData(t.code, t.name, t.short_name)

    def _expected_goals(self, league: _MockLeague, home: str, away: str) -> tuple[float, float]:
        h, a = self._teams[home], self._teams[away]
        return league.mu_home * h.attack * a.defence, league.mu_away * a.attack * h.defence

    def _schedule(self, league: _MockLeague) -> list[tuple[str, int, datetime, str, str]]:
        """(season, round, kickoff, home, away) for the previous and current season."""
        year = _season_start_year(self.current_round_start, league.calendar_year)
        seasons = (
            _season_label(year - 1, league.calendar_year),
            _season_label(year, league.calendar_year),
        )
        offset = timedelta(days=league.day_offset)
        out = []
        if league.type == "cup":
            rounds_per_season = 8
            for s_idx, season in enumerate(seasons):
                start = self.season_start - (1 - s_idx) * 40 * ROUND_SPACING + offset
                for r in range(rounds_per_season):
                    rng = np.random.default_rng(_seed("cup", league.provider_id, season, r))
                    codes = list(rng.permutation([t.code for t in league.teams]))
                    day = start + r * CUP_ROUND_SPACING
                    for j in range(CUP_TIES_PER_ROUND):
                        kickoff = datetime.combine(day.date(), league.kickoff_slots[0], tzinfo=UTC)
                        kickoff += timedelta(days=j % 2)
                        out.append((season, r + 1, kickoff, codes[2 * j], codes[2 * j + 1]))
            return out
        rounds = _round_robin([t.code for t in league.teams])
        per_slot = max(1, -(-len(league.teams) // 2 // len(league.kickoff_slots)))
        prev_start = self.season_start - (len(rounds) + SEASON_BREAK_ROUNDS) * ROUND_SPACING
        for season, start in ((seasons[0], prev_start), (seasons[1], self.season_start)):
            for r_idx, pairs in enumerate(rounds):
                round_start = start + r_idx * ROUND_SPACING + offset
                for j, (home, away) in enumerate(pairs):
                    day = round_start + timedelta(days=j % 4)
                    slot = league.kickoff_slots[min(j // per_slot, len(league.kickoff_slots) - 1)]
                    if league.id_prefix == "":  # Premier League: unchanged pre-v2 schedule
                        slot = league.kickoff_slots[j // 4]
                    kickoff = datetime.combine(day.date(), slot, tzinfo=UTC)
                    out.append((season, r_idx + 1, kickoff, home, away))
        return out

    def _build_fixtures(self, league: _MockLeague) -> list[FixtureData]:
        out: list[FixtureData] = []
        for season, rnd, kickoff, home, away in self._schedule(league):
            pid = f"{league.id_prefix}{season}-r{rnd:02d}-{home}-{away}"
            status, hs, as_ = self._status_and_score(league, pid, home, away, kickoff)
            out.append(
                FixtureData(
                    provider_id=pid,
                    league_provider_id=league.provider_id,
                    season=season,
                    round=rnd,
                    kickoff_at=kickoff,
                    home_team=self._team(home),
                    away_team=self._team(away),
                    status=status,
                    home_score=hs,
                    away_score=as_,
                )
            )
        return out

    def _status_and_score(
        self, league: _MockLeague, pid: str, home: str, away: str, kickoff: datetime
    ) -> tuple[str, int | None, int | None]:
        if self.reference_time >= kickoff + MATCH_DURATION:
            rng = np.random.default_rng(_seed("score", pid))
            lam_h, lam_a = self._expected_goals(league, home, away)
            return "finished", int(rng.poisson(lam_h)), int(rng.poisson(lam_a))
        if self.reference_time >= kickoff:
            return "live", None, None
        return "scheduled", None, None

    def get_fixtures(self, date_from: datetime, date_to: datetime) -> list[FixtureData]:
        return [
            f for fs in self._fixtures.values() for f in fs if date_from <= f.kickoff_at < date_to
        ]

    def get_league_history(self, league: LeagueData) -> list[FixtureData]:
        return list(self._fixtures.get(league.provider_id, []))

    def get_fixtures_by_ids(self, fixture_provider_ids: list[str]) -> list[FixtureData]:
        return [self._by_id[i] for i in dict.fromkeys(fixture_provider_ids) if i in self._by_id]

    # ------------------------------------------------------------------- odds
    def get_odds(self, fixtures: Mapping[str, datetime] | Sequence[str]) -> list[OddsData]:
        out: list[OddsData] = []
        for pid in fixtures:
            fixture = self._by_id.get(pid)
            if fixture is None:
                continue
            for k, offset in enumerate(SNAPSHOT_OFFSETS):
                captured = fixture.kickoff_at - offset
                if captured > self.reference_time:
                    continue  # cannot capture the future
                out.append(self._price(fixture, k, captured))
        return out

    # -------------------------------------------------------------- team news
    @staticmethod
    def _squad(code: str) -> list[PlayerRef]:
        return [
            PlayerRef(f"{code}-P{n:02d}", f"{code} Player {n}", n, pos)
            for n, pos in enumerate(SQUAD_POSITIONS, start=1)
        ]

    def _team_sheet(
        self, fixture: FixtureData, code: str
    ) -> tuple[list[PlayerRef], list[AbsenceData], list[PlayerRef]]:
        """(starting XI, absences, bench) for one team, deterministic per fixture."""
        squad = self._squad(code)
        rng = np.random.default_rng(_seed("team-news", fixture.provider_id, code))
        absences: list[AbsenceData] = []
        unavailable: set[str] = set()
        for player in squad[:11]:
            roll = rng.random()
            if roll < P_OUT:
                status = "out"
            elif roll < P_OUT + P_DOUBTFUL:
                status = "doubtful"
            else:
                continue
            reason = "Injury" if rng.random() < 0.8 else "Suspended"
            absences.append(AbsenceData(fixture.provider_id, code, player, status, reason))
            if status == "out" or rng.random() < 0.5:
                unavailable.add(player.provider_id)
        bench = [p for p in squad[11:]]
        starters: list[PlayerRef] = []
        for player in squad[:11]:
            if player.provider_id not in unavailable:
                starters.append(player)
                continue
            same = next((b for b in bench if b.position == player.position), None)
            replacement = same or bench[0]
            bench.remove(replacement)
            starters.append(replacement)
        return starters, absences, bench

    def get_absences(self, fixtures: Mapping[str, datetime] | Sequence[str]) -> list[AbsenceData]:
        out: list[AbsenceData] = []
        for pid in fixtures:
            f = self._by_id.get(pid)
            if f is None or self.reference_time < f.kickoff_at - ABSENCES_KNOWN:
                continue
            for code in (f.home_team_provider_id, f.away_team_provider_id):
                out.extend(self._team_sheet(f, code)[1])
        return out

    def get_lineups(self, fixture_provider_ids: list[str]) -> list[LineupData]:
        out: list[LineupData] = []
        for pid in fixture_provider_ids:
            f = self._by_id.get(pid)
            if f is None or self.reference_time < f.kickoff_at - LINEUPS_KNOWN:
                continue
            for code in (f.home_team_provider_id, f.away_team_provider_id):
                starters, _, bench = self._team_sheet(f, code)
                out.append(LineupData(pid, code, "4-3-3", tuple(starters), tuple(bench)))
        return out

    def get_appearances(self, fixture_provider_ids: list[str]) -> list[AppearanceData]:
        out: list[AppearanceData] = []
        for pid in fixture_provider_ids:
            f = self._by_id.get(pid)
            if f is None or f.status != "finished":
                continue
            for code in (f.home_team_provider_id, f.away_team_provider_id):
                starters, _, bench = self._team_sheet(f, code)
                rng = np.random.default_rng(_seed("subs", pid, code))
                subbed = rng.choice(len(starters), size=min(3, len(bench)), replace=False)
                minutes = {p.provider_id: 90 for p in starters}
                for k, idx in enumerate(subbed):
                    off = int(rng.integers(55, 86))
                    minutes[starters[idx].provider_id] = off
                    out.append(AppearanceData(pid, code, bench[k], False, 90 - off))
                out.extend(
                    AppearanceData(pid, code, p, True, minutes[p.provider_id]) for p in starters
                )
        return out

    def _price(self, fixture: FixtureData, k: int, captured: datetime) -> OddsData:
        rng = np.random.default_rng(_seed("odds", fixture.provider_id, k))
        league = self._leagues[fixture.league_provider_id]
        lam_h, lam_a = self._expected_goals(
            league, fixture.home_team_provider_id, fixture.away_team_provider_id
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
