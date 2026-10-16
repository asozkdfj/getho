"""StatsBomb open data loader: results + starting XIs + minutes played.

https://github.com/statsbomb/open-data - free for research; any published use
must credit StatsBomb as the data source. The 2015/16 seasons of the Premier
League, La Liga, Serie A and Ligue 1 are complete (one file per match with both
line-ups and every player's position spells), which makes them suitable for
measuring whether line-up information improves the model. Files are cached on
disk so a backtest can be re-run offline.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from edge_ml.core import MatchResult
from edge_ml.forecasters import BacktestMatch, MatchLineups, TeamSheet

logger = logging.getLogger(__name__)

BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
FULL_MATCH = 90


@dataclass(frozen=True, slots=True)
class StatsBombSeason:
    code: str
    name: str
    competition_id: int
    season_id: int
    season: str
    tz: str


# Complete seasons with line-ups (the 2015/16 Bundesliga file holds only 34 matches).
SEASONS: dict[str, StatsBombSeason] = {
    s.code: s
    for s in (
        StatsBombSeason("en.1", "Premier League", 2, 27, "2015-16", "Europe/London"),
        StatsBombSeason("es.1", "La Liga", 11, 27, "2015-16", "Europe/Madrid"),
        StatsBombSeason("it.1", "Serie A", 12, 27, "2015-16", "Europe/Rome"),
        StatsBombSeason("fr.1", "Ligue 1", 7, 27, "2015-16", "Europe/Paris"),
    )
}


def _fetch(url: str, path: Path, timeout: float = 30.0) -> Any:
    if not path.exists():
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return json.loads(path.read_text())


def _clock(value: str | None) -> float | None:
    if not value:
        return None
    mm, ss = value.split(":")[:2]
    return int(mm) + int(ss) / 60


def team_sheet(entry: dict[str, Any]) -> TeamSheet:
    """Starters and minutes from StatsBomb position spells ("from"/"to" match clock)."""
    starters: list[str] = []
    minutes: dict[str, int] = {}
    for player in entry.get("lineup", []):
        spells = player.get("positions") or []
        if not spells:
            continue  # unused substitute
        pid = str(player["player_id"])
        if any(s.get("start_reason") == "Starting XI" for s in spells):
            starters.append(pid)
        start = min(_clock(s.get("from")) or 0.0 for s in spells)
        ends = [_clock(s.get("to")) for s in spells]
        end = FULL_MATCH if any(e is None for e in ends) else max(e for e in ends if e is not None)
        minutes[pid] = max(0, min(round(max(end, start) - start), 130))
    return TeamSheet(tuple(starters), minutes)


def parse_match(
    m: dict[str, Any], lineups: list[dict[str, Any]], season: StatsBombSeason
) -> BacktestMatch | None:
    home_id = m["home_team"]["home_team_id"]
    away_id = m["away_team"]["away_team_id"]
    sheets = {entry["team_id"]: team_sheet(entry) for entry in lineups}
    if home_id not in sheets or away_id not in sheets:
        return None
    if len(sheets[home_id].starters) != 11 or len(sheets[away_id].starters) != 11:
        return None
    kick = time.fromisoformat(m["kick_off"][:8]) if m.get("kick_off") else time(15)
    local = datetime.combine(
        datetime.fromisoformat(m["match_date"]).date(), kick, ZoneInfo(season.tz)
    )
    return BacktestMatch(
        MatchResult(
            home=f"sb{home_id}",
            away=f"sb{away_id}",
            home_goals=int(m["home_score"]),
            away_goals=int(m["away_score"]),
            kickoff_at=local.astimezone(UTC),
            season=season.season,
        ),
        lineups=MatchLineups(sheets[home_id], sheets[away_id]),
    )


def load(code: str, cache_dir: Path, workers: int = 16) -> list[BacktestMatch]:
    season = SEASONS[code]
    root = cache_dir / "statsbomb"
    matches = _fetch(
        f"{BASE_URL}/matches/{season.competition_id}/{season.season_id}.json",
        root / f"matches-{season.competition_id}-{season.season_id}.json",
    )

    def lineup(m: dict[str, Any]) -> list[dict[str, Any]]:
        mid = m["match_id"]
        return _fetch(f"{BASE_URL}/lineups/{mid}.json", root / "lineups" / f"{mid}.json")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        lineups = list(pool.map(lineup, matches))
    out = [bm for m, lu in zip(matches, lineups, strict=True) if (bm := parse_match(m, lu, season))]
    logger.info("statsbomb %s %s: %d matches with line-ups", code, season.season, len(out))
    return out
