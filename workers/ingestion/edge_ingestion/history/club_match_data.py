"""Results + pre-match Bet365 1X2 odds from "Club Football Match Data".

Source: github.com/xgabora/Club-Football-Match-Data-2000-2025 (MIT licence),
a tidy copy of football-data.co.uk results and odds (attribute both). One CSV,
``data/Matches.csv``, cached on disk; the file's SHA-256 goes into every report.

Columns used: Division, MatchDate, MatchTime (UK time), HomeTeam, AwayTeam,
FTHome, FTAway, OddHome, OddDraw, OddAway (Bet365); for the goal markets also
Over25, Under25 (Bet365 over/under 2.5 goals) and HandiSize, HandiHome,
HandiAway (Bet365 Asian handicap: the home team's line and both prices). The exact time the odds
were captured is not documented in the copy; football-data.co.uk collects its
main odds columns some time before kickoff, so treat them as "pre-match market"
rather than as odds seen at the service's 09:00 KST decision.

Seasons are not in the file. Per division a new season starts after a break
of more than 30 days that ends between July and September, so the 2020 COVID
pause (restarts in May/June) and the 2022 World Cup break (restart in December)
stay inside their seasons.
"""

from __future__ import annotations

import csv
import io
import logging
import unicodedata
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from edge_ml.core import MatchResult
from edge_ml.forecasters import BacktestMatch

logger = logging.getLogger(__name__)

URL = (
    "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/"
    "main/data/Matches.csv"
)
CACHE_NAME = "club-football-match-data-Matches.csv"
UK = ZoneInfo("Europe/London")
DEFAULT_KICKOFF = time(15, 0)
SEASON_GAP = timedelta(days=30)
SEASON_START_MONTHS = {7, 8, 9}

# football-data.co.uk division codes of the leagues we verify
DIVISIONS = {
    "en.1": "E0",
    "en.2": "E1",
    "de.1": "D1",
    "de.2": "D2",
    "es.1": "SP1",
    "it.1": "I1",
    "fr.1": "F1",
    "nl.1": "N1",
    "pt.1": "P1",
}


def fetch(cache_dir: Path, timeout: float = 120.0) -> Path:
    path = cache_dir / CACHE_NAME
    if not path.exists():
        logger.info("downloading %s", URL)
        with urllib.request.urlopen(URL, timeout=timeout) as resp:
            data = resp.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


def team_key(name: str) -> str:
    """One spelling per club: the file switches between e.g. "Nott'm Forest" and
    "Nottm Forest", "M'gladbach" and "MGladbach", "Preußen Münster" and
    "Preussen Munster" within a season."""
    name = name.strip().replace("'", "").replace("ß", "ss")
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(ascii_name.split()).casefold()


def _odds(row: dict[str, str]) -> tuple[float, float, float] | None:
    try:
        odds = tuple(float(row[k]) for k in ("OddHome", "OddDraw", "OddAway"))
    except (KeyError, ValueError):
        return None
    return odds if all(o > 1.0 for o in odds) else None  # type: ignore[return-value]


def season_labels(days: list[date]) -> list[str]:
    """Season label ("2023-24") per (sorted) match day of one division."""
    labels: list[str] = []
    start: date | None = None
    previous: date | None = None
    for d in days:
        if start is None or (
            previous is not None and d - previous > SEASON_GAP and d.month in SEASON_START_MONTHS
        ):
            start = d
        labels.append(f"{start.year}-{(start.year + 1) % 100:02d}")
        previous = d
    return labels


def parse(text: str, division: str) -> list[BacktestMatch]:
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r.get("Division") == division]
    played = []
    for r in rows:
        try:
            day = date.fromisoformat(r["MatchDate"])
            hg, ag = int(float(r["FTHome"])), int(float(r["FTAway"]))
        except (KeyError, ValueError):
            continue  # not played / malformed
        kickoff = time.fromisoformat(r["MatchTime"]) if r.get("MatchTime") else DEFAULT_KICKOFF
        played.append((day, kickoff, r, hg, ag))
    played.sort(key=lambda x: (x[0], x[1], x[2]["HomeTeam"]))
    seasons = season_labels([p[0] for p in played])
    return [
        BacktestMatch(
            MatchResult(
                home=team_key(r["HomeTeam"]),
                away=team_key(r["AwayTeam"]),
                home_goals=hg,
                away_goals=ag,
                kickoff_at=datetime.combine(day, kickoff, tzinfo=UK).astimezone(UTC),
                season=season,
            ),
            odds=_odds(r),
        )
        for (day, kickoff, r, hg, ag), season in zip(played, seasons, strict=True)
    ]


def load(
    code: str, first: str, last: str, cache_dir: Path
) -> tuple[list[BacktestMatch], dict[str, int]]:
    """Matches of one league between two seasons (inclusive) and a per-season count."""
    text = fetch(cache_dir).read_text(encoding="utf-8")
    matches = [m for m in parse(text, DIVISIONS[code]) if first <= (m.result.season or "") <= last]
    counts: dict[str, int] = defaultdict(int)
    for m in matches:
        counts[m.result.season or ""] += 1
    return matches, dict(sorted(counts.items()))


# ------------------------------------------------------------------ goal markets
@dataclass(frozen=True, slots=True)
class GoalMarketOdds:
    over25: float | None
    under25: float | None
    handicap: float | None  # home team's Asian handicap line, e.g. -0.75
    handicap_home: float | None
    handicap_away: float | None


def restore_quarter_line(value: float) -> float | None:
    """The copy rounds quarter lines to one decimal (-0.25 -> -0.3, -0.75 -> -0.8,
    1.25 -> 1.3). Map them back; anything that is not a whole, half or quarter
    line after that is unknown (None)."""
    whole, frac = divmod(round(abs(value), 2), 1)
    frac = round(frac, 2)
    frac = {0.3: 0.25, 0.8: 0.75}.get(frac, frac)
    if frac not in (0.0, 0.25, 0.5, 0.75):
        return None
    line = whole + frac
    return -line if value < 0 else line


def _price(row: dict[str, str], key: str) -> float | None:
    try:
        v = float(row[key])
    except (KeyError, ValueError):
        return None
    return v if v > 1.0 else None


def _goal_odds(row: dict[str, str]) -> GoalMarketOdds:
    try:
        line = restore_quarter_line(float(row["HandiSize"]))
    except (KeyError, ValueError):
        line = None
    return GoalMarketOdds(
        over25=_price(row, "Over25"),
        under25=_price(row, "Under25"),
        handicap=line,
        handicap_home=_price(row, "HandiHome"),
        handicap_away=_price(row, "HandiAway"),
    )


MatchKey = tuple[datetime, str, str]


def match_key(result: MatchResult) -> MatchKey:
    return (result.kickoff_at, result.home, result.away)


def load_goal_odds(code: str, cache_dir: Path) -> dict[MatchKey, GoalMarketOdds]:
    """Over/under 2.5 and Asian handicap prices per match, keyed like ``load``."""
    text = fetch(cache_dir).read_text(encoding="utf-8")
    out: dict[MatchKey, GoalMarketOdds] = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("Division") != DIVISIONS[code]:
            continue
        try:
            day = date.fromisoformat(r["MatchDate"])
        except (KeyError, ValueError):
            continue
        kickoff = time.fromisoformat(r["MatchTime"]) if r.get("MatchTime") else DEFAULT_KICKOFF
        at = datetime.combine(day, kickoff, tzinfo=UK).astimezone(UTC)
        out[(at, team_key(r["HomeTeam"]), team_key(r["AwayTeam"]))] = _goal_odds(r)
    return out
