"""football-data.co.uk CSV loader (results + bookmaker prices).

Download season files yourself (e.g. https://www.football-data.co.uk/mmz4281/2425/E0.csv)
and check that site's terms. Closing prices are preferred because they are the
market's final, best-informed view; we fall back to opening/average prices.
"""

from __future__ import annotations

import csv
import hashlib
import io
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from edge_ml.core import MatchResult
from edge_ml.forecasters import BacktestMatch

UK = ZoneInfo("Europe/London")
# (home, draw, away) column triples in order of preference
ODDS_COLUMNS = [
    ("PSCH", "PSCD", "PSCA"),  # Pinnacle closing
    ("AvgCH", "AvgCD", "AvgCA"),  # market average closing
    ("B365CH", "B365CD", "B365CA"),  # Bet365 closing
    ("PSH", "PSD", "PSA"),  # Pinnacle opening
    ("AvgH", "AvgD", "AvgA"),
    ("B365H", "B365D", "B365A"),
]


def _date(value: str) -> datetime:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt)  # noqa: DTZ007 (date only, tz added below)
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {value!r}")


def _odds(row: dict[str, str]) -> tuple[float, float, float] | None:
    for cols in ODDS_COLUMNS:
        try:
            prices = tuple(float(row[c]) for c in cols)
        except (KeyError, ValueError):
            continue
        if all(p > 1.0 for p in prices):
            return prices  # type: ignore[return-value]
    return None


def parse_text(text: str, season: str) -> list[BacktestMatch]:
    out: list[BacktestMatch] = []
    for row in csv.DictReader(io.StringIO(text)):
        if not row.get("HomeTeam") or not row.get("FTHG"):
            continue
        kick = time.fromisoformat(row["Time"]) if row.get("Time") else time(15, 0)
        local = datetime.combine(_date(row["Date"]).date(), kick, tzinfo=UK)
        out.append(
            BacktestMatch(
                MatchResult(
                    home=row["HomeTeam"],
                    away=row["AwayTeam"],
                    home_goals=int(row["FTHG"]),
                    away_goals=int(row["FTAG"]),
                    kickoff_at=local.astimezone(UTC),
                    season=season,
                ),
                odds=_odds(row),
            )
        )
    return out


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_csv(path: Path, season: str) -> list[BacktestMatch]:
    return parse_text(decode(path.read_bytes()), season)


def load_dir(directory: Path) -> list[BacktestMatch]:
    """Load every ``<season>.csv`` (e.g. 2024-25.csv) in a directory."""
    matches: list[BacktestMatch] = []
    for path in sorted(directory.glob("*.csv")):
        matches.extend(parse_csv(path, path.stem))
    return matches


# ------------------------------------------------------------------ season files
SEASON_URL = "https://www.football-data.co.uk/mmz4281/{code}/{division}.csv"


def season_code(season: str) -> str:
    """'2026-27' -> '2627' (the site's folder name)."""
    return season[2:4] + season[5:7]


def fetch_season(cache_dir: Path, season: str, division: str, timeout: float = 60.0) -> Path:
    """One division-season CSV, downloaded once and cached."""
    path = cache_dir / f"football-data-{season_code(season)}-{division}.csv"
    if not path.exists():
        url = SEASON_URL.format(code=season_code(season), division=division)
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


@dataclass(frozen=True, slots=True)
class SeasonFile:
    season: str
    sha256: str
    rows: int  # fixture rows in the file
    played: int  # rows with a result
    no_result: int  # listed without a result (postponed / abandoned / not yet played)


def load_seasons(
    division: str, seasons: list[str], cache_dir: Path, key: Any = None
) -> tuple[list[BacktestMatch], list[SeasonFile]]:
    """Played matches of several seasons of one division (team names passed
    through ``key`` when given, so spellings agree across seasons) and a record
    of every file read."""
    matches: list[BacktestMatch] = []
    files: list[SeasonFile] = []
    for season in seasons:
        raw = fetch_season(cache_dir, season, division).read_bytes()
        text = decode(raw)
        listed = [r for r in csv.DictReader(io.StringIO(text)) if r.get("HomeTeam")]
        played = parse_text(text, season)
        if key is not None:
            played = [
                BacktestMatch(
                    MatchResult(
                        home=key(m.result.home),
                        away=key(m.result.away),
                        home_goals=m.result.home_goals,
                        away_goals=m.result.away_goals,
                        kickoff_at=m.result.kickoff_at,
                        season=m.result.season,
                    ),
                    odds=m.odds,
                )
                for m in played
            ]
        matches.extend(played)
        files.append(
            SeasonFile(
                season,
                hashlib.sha256(raw).hexdigest(),
                len(listed),
                len(played),
                len(listed) - len(played),
            )
        )
    return matches, files
