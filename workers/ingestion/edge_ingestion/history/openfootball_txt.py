"""Cup and European fixtures from openfootball's Football.TXT repositories.

Used only for schedule features (rest days, fixture congestion, extra time) of
English clubs: the league files (football.json) do not contain the FA Cup, the
EFL Cup or European matches that a team also played.

Sources (public domain, CC0), cached on disk like the league files:
  openfootball/england          {season}/facup.txt, {season}/eflcup.txt
  openfootball/champions-league {season}/cl.txt, el.txt, conf.txt

Coverage checked 2026-10-16: FA Cup and EFL Cup 2018-19..2024-25 (2025-26 not
published); Champions League 2018-19..2025-26; Europa League 2020-21..2024-25;
Conference League (founded 2021-22) 2021-22..2024-25. Missing files are
reported, never filled in.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from edge_ingestion.history.openfootball import normalize_team

logger = logging.getLogger(__name__)

SOURCES: dict[str, tuple[str, str]] = {
    # competition -> (repository, file name)
    "facup": ("england", "facup.txt"),
    "eflcup": ("england", "eflcup.txt"),
    "cl": ("champions-league", "cl.txt"),
    "el": ("champions-league", "el.txt"),
    "conf": ("champions-league", "conf.txt"),
}
RAW_URL = "https://raw.githubusercontent.com/openfootball/{repo}/master/{season}/{file}"
# Competitions that did not exist yet are not "missing".
FOUNDED = {"conf": "2021-22"}
UK = ZoneInfo("Europe/London")
CET = ZoneInfo("Europe/Paris")  # European competition times are central European

MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}
DATE_LINE = re.compile(
    r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([A-Z][a-z]{2}) (\d{1,2})(?: (\d{4}))?\s*$"
)
HEADER_YEAR = re.compile(r"^#\s*Date\s+\w{3} \w{3} \d{1,2} (\d{4})")
MATCH_LINE = re.compile(
    r"^\s*(?:(\d{1,2})[:.](\d{2})\s+)?(?P<home>\S.*?)\s+v\s+(?P<away>\S.*?)\s{2,}(?P<rest>\S.*)$"
)
SCORE = re.compile(r"^(\d+)-(\d+)")
COUNTRY = re.compile(r"\s*\([A-Z]{3}\)$")


@dataclass(frozen=True, slots=True)
class CupMatch:
    competition: str
    season: str
    home: str  # normalized like the league files ("Arsenal", "Manchester City")
    away: str
    kickoff_at: datetime  # UTC; 15:00 local when the file has no time
    extra_time: bool


def team_key(name: str) -> str:
    return normalize_team(COUNTRY.sub("", name.strip()))


def parse(text: str, competition: str, season: str) -> list[CupMatch]:
    """Played matches of one Football.TXT file (unplayed lines are skipped)."""
    tz = CET if competition in {"cl", "el", "conf"} else UK
    year = int(season[:4])
    month = 0
    day: date | None = None
    kickoff = time(15, 0)
    out: list[CupMatch] = []
    for line in text.splitlines():
        if m := HEADER_YEAR.match(line):
            year = int(m.group(1))
            continue
        if line.lstrip().startswith(("#", "=", "▪")):
            continue
        if m := DATE_LINE.match(line):
            mon = MONTHS[m.group(1)]
            if m.group(3):
                year = int(m.group(3))
            elif mon < month:
                year += 1  # the season crossed new year without an explicit year
            month = mon
            day = date(year, mon, int(m.group(2)))
            kickoff = time(15, 0)
            continue
        m = MATCH_LINE.match(line)
        if not m or day is None:
            continue
        if m.group(1):
            kickoff = time(int(m.group(1)), int(m.group(2)))
        if not SCORE.match(m.group("rest")):
            continue  # postponed / not played
        local = datetime.combine(day, kickoff, tzinfo=tz)
        out.append(
            CupMatch(
                competition=competition,
                season=season,
                home=team_key(m.group("home")),
                away=team_key(m.group("away")),
                kickoff_at=local.astimezone(UTC),
                extra_time="a.e.t." in m.group("rest"),
            )
        )
    return out


def _fetch(competition: str, season: str, cache_dir: Path, timeout: float = 30.0) -> str | None:
    repo, file = SOURCES[competition]
    path = cache_dir / f"openfootball-txt-{competition}-{season}.txt"
    missing = path.with_suffix(".missing")
    if path.exists():
        return path.read_text(encoding="utf-8")
    if missing.exists():
        return None
    url = RAW_URL.format(repo=repo, season=season, file=file)
    try:
        logger.info("downloading %s", url)
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        path.parent.mkdir(parents=True, exist_ok=True)
        missing.write_text(url)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return data


def load(
    seasons: list[str], cache_dir: Path, competitions: list[str] | None = None
) -> tuple[list[CupMatch], list[str]]:
    """All played cup/European matches of the seasons, plus a list of missing files."""
    matches: list[CupMatch] = []
    missing: list[str] = []
    for season in seasons:
        for comp in competitions or list(SOURCES):
            if season < FOUNDED.get(comp, ""):
                continue
            text = _fetch(comp, season, cache_dir)
            if text is None:
                missing.append(f"{comp} {season}")
                continue
            parsed = parse(text, comp, season)
            logger.info("openfootball txt %s %s: %d played matches", comp, season, len(parsed))
            matches.extend(parsed)
    return matches, missing
