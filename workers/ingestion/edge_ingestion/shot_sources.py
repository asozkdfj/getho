"""`edge compare-shots` - are API-Football's shots on target the same numbers
football-data.co.uk publishes?

The shot-based form experiment (ADR-034) was fitted on football-data.co.uk
shots on target; the service would feed it API-Football `match_statistics`.
This joins the two sources match by match and reports how well they agree.
Measurement only.

Join: API-Football league -> football-data division (below), then the UK match
date and the final score, and among those candidates the best team-name
similarity; at least one of the two names must match (difflib ratio >= 0.5,
so "Wolves" next to a matching opponent still joins). Anything else is
unmatched and counted. The features are relative to the league average of the same source, so
a proportional scale difference would cancel; a weak per-match correlation
would not.
"""

from __future__ import annotations

import difflib
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from edge_api.db.models import Fixture, FixtureStatus, League
from edge_api.services import queries
from edge_ingestion.history import football_data

# API-Football league id -> football-data.co.uk division
DIVISIONS = {
    "39": "E0",
    "40": "E1",
    "78": "D1",
    "79": "D2",
    "140": "SP1",
    "135": "I1",
    "61": "F1",
    "88": "N1",
    "94": "P1",
}
MIN_NAME_SIMILARITY = 0.5


def _norm(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = [w for w in ascii_name.casefold().replace("'", "").replace(".", " ").split()]
    drop = {"fc", "cf", "afc", "sc", "ac", "sv", "vfb", "vfl", "fsv", "tsg", "1.", "club", "de"}
    return " ".join(w for w in words if w not in drop)


def _similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if a and b and (a in b or b in a):
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def season_of(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _fd_rows(division: str, seasons: set[str], cache_dir: Path) -> dict[tuple, list[dict]]:
    """(UK date, home goals, away goals) -> football-data rows with shots."""
    import csv
    import io

    out: dict[tuple, list[dict]] = defaultdict(list)
    for season in sorted(seasons):
        text = football_data.decode(
            football_data.fetch_season(cache_dir, season, division).read_bytes()
        )
        for row in csv.DictReader(io.StringIO(text)):
            try:
                day = football_data._date(row["Date"]).date()
                key = (day, int(row["FTHG"]), int(row["FTAG"]))
                shots = (float(row["HST"]), float(row["AST"]), float(row["HS"]), float(row["AS"]))
            except (KeyError, TypeError, ValueError):
                continue
            out[key].append({"home": row["HomeTeam"], "away": row["AwayTeam"], "stats": shots})
    return out


def compare_shot_sources(
    session: Session, provider: str, *, now: datetime, days: int, cache_dir: Path
) -> dict[str, Any]:
    leagues = {
        lg.id: lg
        for lg in session.scalars(
            select(League).where(League.provider == provider, League.provider_id.in_(DIVISIONS))
        )
    }
    fixtures = session.scalars(
        select(Fixture).where(
            Fixture.provider == provider,
            Fixture.league_id.in_(leagues),
            Fixture.status == FixtureStatus.FINISHED.value,
            Fixture.kickoff_at >= now - timedelta(days=days),
            Fixture.kickoff_at <= now,
        )
    ).all()
    stats: dict[int, dict[int, Any]] = defaultdict(dict)
    for s in queries.latest_statistics(session, [f.id for f in fixtures]):
        stats[s.fixture_id][s.team_id] = s

    by_division: dict[str, list[Fixture]] = defaultdict(list)
    for f in fixtures:
        both = stats.get(f.id, {})
        h, a = both.get(f.home_team_id), both.get(f.away_team_id)
        if h is None or a is None or h.shots_on_target is None or a.shots_on_target is None:
            continue
        by_division[DIVISIONS[leagues[f.league_id].provider_id]].append(f)

    pairs: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    counts: dict[str, dict[str, int]] = {}
    for division, fs in sorted(by_division.items()):
        uk_days = {f: f.kickoff_at.astimezone(football_data.UK).date() for f in fs}
        fd = _fd_rows(division, {season_of(d) for d in uk_days.values()}, cache_dir)
        c = {"with_api_stats": len(fs), "matched": 0, "unmatched": 0}
        for f in fs:
            cands = fd.get((uk_days[f], f.home_score, f.away_score), [])
            best = max(
                cands,
                key=lambda r: (
                    _similarity(f.home_team.name, r["home"])
                    + _similarity(f.away_team.name, r["away"])
                ),
                default=None,
            )
            if (
                best is None
                or max(
                    _similarity(f.home_team.name, best["home"]),
                    _similarity(f.away_team.name, best["away"]),
                )
                < MIN_NAME_SIMILARITY
            ):
                c["unmatched"] += 1
                continue
            c["matched"] += 1
            h, a = stats[f.id][f.home_team_id], stats[f.id][f.away_team_id]
            hst, ast, hs, as_ = best["stats"]
            pairs[division].append((float(h.shots_on_target), hst, float(h.shots or np.nan), hs))
            pairs[division].append((float(a.shots_on_target), ast, float(a.shots or np.nan), as_))
        counts[division] = c

    report: dict[str, Any] = {
        "provider": provider,
        "window_days": days,
        "generated_at": now.isoformat(),
        "note": "API-Football vs football-data.co.uk, same matches; measurement only",
        "counts": counts,
        "per_division": {d: _agreement(p) for d, p in sorted(pairs.items())},
        "all": _agreement([x for p in pairs.values() for x in p]),
    }
    return report


def _agreement(pairs: list[tuple[float, float, float, float]]) -> dict[str, Any]:
    if not pairs:
        return {"team_rows": 0}
    arr = np.array(pairs, dtype=float)

    def block(api: np.ndarray, fd: np.ndarray) -> dict[str, Any]:
        ok = ~(np.isnan(api) | np.isnan(fd))
        api, fd = api[ok], fd[ok]
        if len(api) < 2:
            return {"n": len(api)}
        return {
            "n": len(api),
            "mean_api_football": float(api.mean()),
            "mean_football_data": float(fd.mean()),
            "ratio": float(api.mean() / fd.mean()) if fd.mean() else None,
            "correlation": float(np.corrcoef(api, fd)[0, 1]) if api.std() and fd.std() else None,
            "mean_abs_diff": float(np.abs(api - fd).mean()),
            "share_equal": float((api == fd).mean()),
        }

    return {
        "team_rows": len(arr),
        "shots_on_target": block(arr[:, 0], arr[:, 1]),
        "shots": block(arr[:, 2], arr[:, 3]),
    }
