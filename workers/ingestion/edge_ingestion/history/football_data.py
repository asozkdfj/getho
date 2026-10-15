"""football-data.co.uk CSV loader (results + bookmaker prices).

Download season files yourself (e.g. https://www.football-data.co.uk/mmz4281/2425/E0.csv)
and check that site's terms. Closing prices are preferred because they are the
market's final, best-informed view; we fall back to opening/average prices.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, time
from pathlib import Path
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


def parse_csv(path: Path, season: str) -> list[BacktestMatch]:
    out: list[BacktestMatch] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
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


def load_dir(directory: Path) -> list[BacktestMatch]:
    """Load every ``<season>.csv`` (e.g. 2024-25.csv) in a directory."""
    matches: list[BacktestMatch] = []
    for path in sorted(directory.glob("*.csv")):
        matches.extend(parse_csv(path, path.stem))
    return matches
