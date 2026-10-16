"""openfootball/football.json loader (league results, public domain / CC0).

https://github.com/openfootball/football.json - one JSON file per league and
season with date, local kick-off time and full-time score. No odds: use it for
model evaluation; market comparisons need a dataset with prices
(football_data.py). Data is cached on disk so a backtest can be re-run offline
and reproducibly.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from edge_ml.core import MatchResult
from edge_ml.forecasters import BacktestMatch

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{code}.json"
)
UK = ZoneInfo("Europe/London")
DEFAULT_KICKOFF = time(15, 0)  # used only when a match has no time


@dataclass(frozen=True, slots=True)
class HistoryLeague:
    code: str  # openfootball file name, e.g. "de.1"
    name: str
    country: str
    tz: str  # kick-off times in the files are local times
    api_football_id: str


# Leagues with complete 2018-19..2025-26 files (checked 2026-10-15).
LEAGUES: dict[str, HistoryLeague] = {
    lg.code: lg
    for lg in (
        HistoryLeague("en.1", "Premier League", "England", "Europe/London", "39"),
        HistoryLeague("en.2", "Championship", "England", "Europe/London", "40"),
        HistoryLeague("de.1", "Bundesliga", "Germany", "Europe/Berlin", "78"),
        HistoryLeague("de.2", "2. Bundesliga", "Germany", "Europe/Berlin", "79"),
        HistoryLeague("es.1", "La Liga", "Spain", "Europe/Madrid", "140"),
        HistoryLeague("it.1", "Serie A", "Italy", "Europe/Rome", "135"),
        HistoryLeague("fr.1", "Ligue 1", "France", "Europe/Paris", "61"),
        HistoryLeague("nl.1", "Eredivisie", "Netherlands", "Europe/Amsterdam", "88"),
        HistoryLeague("pt.1", "Primeira Liga", "Portugal", "Europe/Lisbon", "94"),
        HistoryLeague("at.1", "Austrian Bundesliga", "Austria", "Europe/Vienna", "218"),
    )
}


def normalize_team(name: str) -> str:
    """Stable team key across seasons: the source spells the same club as
    'Manchester City' in some seasons and 'Manchester City FC' in others."""
    name = name.strip()
    for suffix in (" AFC", " FC"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    if name.startswith("AFC "):
        name = name[4:]
    return name


def validate_season(
    matches: list[BacktestMatch], season: str, *, expected_teams: int | None = 20
) -> list[str]:
    """Integrity checks. With ``expected_teams`` the season must be a complete double
    round robin of that size (EPL); without it only generic checks run (leagues
    with split formats or seasons cut short, e.g. 2019-20, are reported, not fixed)."""
    problems: list[str] = []
    teams = {m.result.home for m in matches} | {m.result.away for m in matches}
    pairs = [(m.result.home, m.result.away) for m in matches]
    n = expected_teams or len(teams)
    if expected_teams is not None and len(teams) != expected_teams:
        problems.append(f"{season}: expected {expected_teams} teams, found {len(teams)}")
    if expected_teams is None and matches and len(set(pairs)) != len(pairs):
        # split-format leagues (e.g. Austria) legitimately repeat pairings
        problems.append(f"{season}: repeated pairings (split format?)")
    elif expected_teams is not None and len(set(pairs)) != len(pairs):
        problems.append(f"{season}: duplicated fixtures")
    if matches and len(matches) != n * (n - 1):
        problems.append(
            f"{season}: {len(matches)} finished matches, a double round robin of "
            f"{n} teams has {n * (n - 1)}"
        )
    return problems


def season_labels(first: str, last: str) -> list[str]:
    """'2018-19'..'2020-21' -> ['2018-19', '2019-20', '2020-21']."""
    start, end = int(first[:4]), int(last[:4])
    if end < start:
        raise ValueError("last season is before first season")
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start, end + 1)]


def _fetch(season: str, cache_dir: Path, code: str = "en.1", timeout: float = 30.0) -> dict:
    path = cache_dir / f"openfootball-{code.replace('.', '')}-{season}.json"
    if not path.exists():
        url = BASE_URL.format(season=season, code=code)
        logger.info("downloading %s", url)
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return json.loads(path.read_text())


def parse_season(payload: dict, season: str, tz: ZoneInfo = UK) -> list[BacktestMatch]:
    out: list[BacktestMatch] = []
    for m in payload.get("matches", []):
        score = m.get("score")
        # most seasons use {"ft": [h, a], "ht": [...]}; some entries are a bare [h, a]
        ft = score.get("ft") if isinstance(score, dict) else score
        if not ft or len(ft) != 2 or ft[0] is None or ft[1] is None:
            continue  # not played (yet), postponed or abandoned
        local_time = time.fromisoformat(m["time"]) if m.get("time") else DEFAULT_KICKOFF
        local = datetime.combine(datetime.fromisoformat(m["date"]).date(), local_time, tzinfo=tz)
        out.append(
            BacktestMatch(
                MatchResult(
                    home=normalize_team(m["team1"]),
                    away=normalize_team(m["team2"]),
                    home_goals=int(ft[0]),
                    away_goals=int(ft[1]),
                    kickoff_at=local.astimezone(UTC),
                    season=season,
                )
            )
        )
    return out


def load(
    first: str,
    last: str,
    cache_dir: Path,
    code: str = "en.1",
    warnings: list[str] | None = None,
) -> list[BacktestMatch]:
    league = LEAGUES.get(code)
    tz = ZoneInfo(league.tz) if league else UK
    matches: list[BacktestMatch] = []
    for season in season_labels(first, last):
        parsed = parse_season(_fetch(season, cache_dir, code), season, tz)
        logger.info("openfootball %s %s: %d finished matches", code, season, len(parsed))
        expected = 20 if code == "en.1" else None
        for problem in validate_season(parsed, season, expected_teams=expected):
            logger.warning("data check %s: %s", code, problem)
            if warnings is not None:
                warnings.append(problem)
        matches.extend(parsed)
    return matches
