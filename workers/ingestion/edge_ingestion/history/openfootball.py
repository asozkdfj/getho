"""openfootball/football.json loader (EPL results, public domain / CC0).

https://github.com/openfootball/football.json - one JSON file per season with
date, local kick-off time (UK) and full-time score. No odds: use it for model
evaluation; market comparisons need a dataset with prices (football_data.py).
Data is cached on disk so a backtest can be re-run offline and reproducibly.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from edge_ml.core import MatchResult
from edge_ml.forecasters import BacktestMatch

logger = logging.getLogger(__name__)

BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master/{season}/en.1.json"
UK = ZoneInfo("Europe/London")
DEFAULT_KICKOFF = time(15, 0)  # used only when a match has no time


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


def validate_season(matches: list[BacktestMatch], season: str) -> list[str]:
    """Integrity checks for a complete double round-robin season."""
    problems: list[str] = []
    teams = {m.result.home for m in matches} | {m.result.away for m in matches}
    pairs = [(m.result.home, m.result.away) for m in matches]
    if len(teams) != 20:
        problems.append(f"{season}: expected 20 teams, found {len(teams)}")
    if len(set(pairs)) != len(pairs):
        problems.append(f"{season}: duplicated fixtures")
    if len(matches) not in (0, 380):
        problems.append(f"{season}: {len(matches)} finished matches (incomplete season)")
    return problems


def season_labels(first: str, last: str) -> list[str]:
    """'2018-19'..'2020-21' -> ['2018-19', '2019-20', '2020-21']."""
    start, end = int(first[:4]), int(last[:4])
    if end < start:
        raise ValueError("last season is before first season")
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start, end + 1)]


def _fetch(season: str, cache_dir: Path, timeout: float = 30.0) -> dict:
    path = cache_dir / f"openfootball-en1-{season}.json"
    if not path.exists():
        url = BASE_URL.format(season=season)
        logger.info("downloading %s", url)
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return json.loads(path.read_text())


def parse_season(payload: dict, season: str) -> list[BacktestMatch]:
    out: list[BacktestMatch] = []
    for m in payload.get("matches", []):
        score = m.get("score")
        # most seasons use {"ft": [h, a], "ht": [...]}; some entries are a bare [h, a]
        ft = score.get("ft") if isinstance(score, dict) else score
        if not ft or len(ft) != 2 or ft[0] is None or ft[1] is None:
            continue  # not played (yet), postponed or abandoned
        local_time = time.fromisoformat(m["time"]) if m.get("time") else DEFAULT_KICKOFF
        local = datetime.combine(datetime.fromisoformat(m["date"]).date(), local_time, tzinfo=UK)
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


def load(first: str, last: str, cache_dir: Path) -> list[BacktestMatch]:
    matches: list[BacktestMatch] = []
    for season in season_labels(first, last):
        parsed = parse_season(_fetch(season, cache_dir), season)
        logger.info("openfootball %s: %d finished matches", season, len(parsed))
        for problem in validate_season(parsed, season):
            logger.warning("data check: %s", problem)
        matches.extend(parsed)
    return matches
