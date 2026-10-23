"""`edge availability-readiness` - how much player data a player-availability
experiment could use (counts only; no result or score is read).

Codex's model direction review (2026-10-21) puts player availability next, but
asks for the amount, gaps and observation times of the data first. This report
answers that before any protocol threshold is fixed:

Past matches (line-up time, replayable)
  Per league and season: finished fixtures, fixtures with player minutes for
  both teams, with exactly 11 starters each ("full sheets"), and with enough
  earlier full sheets for both teams to tell the usual XI apart (the
  line-up strength of ADR-014 needs MIN_MATCHES). Minutes collected long after
  the match (``edge backfill-appearances``) are counted apart from those stored
  right after it; both are facts known after the final whistle, but only the
  starting XI is known before kickoff (about an hour before).

Live collection (morning availability, forward only)
  Absence reports carry when they were captured, so only fixtures collected
  live can say what was known at 09:00. A report counts from when it was both
  captured and stored. For those: fixtures whose two teams had an absence
  report before kickoff (and how early), whether both were in by the 09:00
  decision of the fixture's pick day (and how old), and fixtures whose two
  official line-ups were in before kickoff (and how early). Past absence lists
  without a capture time cannot be replayed honestly, so they are not counted
  as morning data.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import (
    Fixture,
    FixtureStatus,
    League,
    PlayerAppearance,
    TeamNewsKind,
    TeamNewsSnapshot,
)
from edge_api.services.leagues import verified_league_ids
from edge_api.services.picks import local_day
from edge_ml.lineups import MIN_MATCHES

# Minutes stored within this time after kickoff count as collected live.
LIVE_WINDOW = timedelta(days=2)


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", type=Path, help="write the JSON report here")


def _sheets(session: Session, provider: str) -> dict[tuple[int, int], tuple[int, datetime]]:
    """(fixture, team) -> (starters, last stored) from player minutes."""
    rows = session.execute(
        select(
            PlayerAppearance.fixture_id,
            PlayerAppearance.team_id,
            func.sum(case((PlayerAppearance.started, 1), else_=0)),
            func.max(PlayerAppearance.created_at),
        )
        .where(PlayerAppearance.provider == provider)
        .group_by(PlayerAppearance.fixture_id, PlayerAppearance.team_id)
    )
    return {(fid, tid): (int(n), stored) for fid, tid, n, stored in rows}


def _first_captured(session: Session, kind: TeamNewsKind) -> dict[tuple[int, int], datetime]:
    """(fixture, team) -> first moment a ``kind`` snapshot was available before
    kickoff. A snapshot is available once it was both captured and stored (the
    later of the two): one captured early but stored late was not usable early
    (Codex QA AVAIL-TIME-1)."""
    available = func.greatest(TeamNewsSnapshot.captured_at, TeamNewsSnapshot.created_at)
    rows = session.execute(
        select(TeamNewsSnapshot.fixture_id, TeamNewsSnapshot.team_id, func.min(available))
        .join(Fixture, Fixture.id == TeamNewsSnapshot.fixture_id)
        .where(TeamNewsSnapshot.kind == kind.value, available < Fixture.kickoff_at)
        .group_by(TeamNewsSnapshot.fixture_id, TeamNewsSnapshot.team_id)
    )
    return {(fid, tid): at for fid, tid, at in rows}


def _at_decision(
    fixtures: list[Fixture],
    first: dict[tuple[int, int], datetime],
    since: datetime | None,
    settings: Settings,
    scope: set[int],
) -> dict[str, Any]:
    """Absences known by the 09:00 decision of each fixture's pick day.

    Counted for decisions from ``since`` (the first absence report ever
    captured: collection had not started before) and only in ``scope``, the
    leagues absences are collected for (any report ever stored); other leagues
    are only counted (``out_of_scope_fixtures``), since 0 there means nothing.
    ``age`` is how old the later team's first report was at the decision."""
    if since is None:
        return {"since": None, "fixtures": 0, "both_teams": 0, "leagues": []}
    per: dict[str, dict[str, Any]] = {}
    ages: list[float] = []
    out_of_scope = 0
    for f in fixtures:
        decision = local_day(f.kickoff_at, settings).publish_at
        if decision < since:
            continue
        if f.league_id not in scope:
            out_of_scope += 1
            continue
        row = per.setdefault(
            f.league.provider_id,
            {"league": f"{f.league.country} - {f.league.name}", "fixtures": 0, "both_teams": 0},
        )
        row["fixtures"] += 1
        home, away = first.get((f.id, f.home_team_id)), first.get((f.id, f.away_team_id))
        if home and away and max(home, away) <= decision:
            row["both_teams"] += 1
            ages.append((decision - max(home, away)).total_seconds() / 3600)
    leagues = sorted(per.values(), key=lambda r: (-r["fixtures"], r["league"]))
    return {
        "since": since.isoformat(),
        "decision": f"{settings.pick_publish_hour:02d}:00 {settings.pick_tz} of the pick day",
        "fixtures": sum(r["fixtures"] for r in leagues),
        "both_teams": sum(r["both_teams"] for r in leagues),
        "median_age_hours": round(statistics.median(ages), 2) if ages else None,
        "age_basis": "the later team's FIRST report (not the freshest one at the decision)",
        "out_of_scope_fixtures": out_of_scope,
        "leagues": leagues,
    }


def _lead_hours(fixtures: list[Fixture], first: dict[tuple[int, int], datetime]) -> list[float]:
    """Hours before kickoff when both teams' snapshots were in (the later one)."""
    out = []
    for f in fixtures:
        home, away = first.get((f.id, f.home_team_id)), first.get((f.id, f.away_team_id))
        if home and away:
            out.append((f.kickoff_at - max(home, away)).total_seconds() / 3600)
    return out


def _spread(hours: list[float]) -> dict[str, Any]:
    if not hours:
        return {"fixtures": 0, "median_hours_before": None, "min_hours_before": None}
    return {
        "fixtures": len(hours),
        "median_hours_before": round(statistics.median(hours), 2),
        "min_hours_before": round(min(hours), 2),
    }


def readiness(session: Session, provider: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings(data_provider=provider)
    sheets = _sheets(session, provider)
    fixtures = session.scalars(
        select(Fixture)
        .join(League, League.id == Fixture.league_id)
        .where(Fixture.provider == provider, Fixture.status == FixtureStatus.FINISHED.value)
        .order_by(Fixture.kickoff_at, Fixture.id)
    ).all()
    verified = verified_league_ids(session, provider)

    prior_full: dict[int, int] = defaultdict(int)  # team -> earlier full sheets (any league)
    seasons: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
    names: dict[str, str] = {}
    for f in fixtures:
        key = f.league.provider_id
        names[key] = f"{f.league.country} - {f.league.name}"
        row = seasons[key].setdefault(
            f.season or "?",
            {
                "finished": 0,
                "with_sheets": 0,
                "full_xi": 0,
                "strength_ready": 0,
                "full_xi_live": 0,
                "full_xi_backfill": 0,
            },
        )
        row["finished"] += 1
        home, away = sheets.get((f.id, f.home_team_id)), sheets.get((f.id, f.away_team_id))
        if not home or not away:
            continue
        row["with_sheets"] += 1
        if home[0] != 11 or away[0] != 11:
            continue
        row["full_xi"] += 1
        live = max(home[1], away[1]) <= f.kickoff_at + LIVE_WINDOW
        row["full_xi_live" if live else "full_xi_backfill"] += 1
        if min(prior_full[f.home_team_id], prior_full[f.away_team_id]) >= MIN_MATCHES:
            row["strength_ready"] += 1
        prior_full[f.home_team_id] += 1
        prior_full[f.away_team_id] += 1

    leagues = []
    for key in sorted(seasons, key=lambda k: (k not in verified, names[k])):
        per_season = dict(sorted(seasons[key].items()))
        totals = {
            k: sum(s[k] for s in per_season.values()) for k in next(iter(per_season.values()))
        }
        leagues.append(
            {
                "provider_id": key,
                "league": names[key],
                "verified": key in verified,
                "totals": totals,
                "seasons": per_season,
            }
        )

    absences = _first_captured(session, TeamNewsKind.ABSENCES)
    ready_verified = sum(lg["totals"]["strength_ready"] for lg in leagues if lg["verified"])
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "provider": provider,
        "outcome_blind": True,
        "protocol": __doc__,
        "rules": {
            "full_xi": "exactly 11 starters stored for both teams",
            "strength_ready": f"full XI and both teams have {MIN_MATCHES}+ earlier full sheets",
            "live_window_hours": LIVE_WINDOW.total_seconds() / 3600,
        },
        "line_up_time": {
            "strength_ready_verified_leagues": ready_verified,
            "strength_ready_all_leagues": sum(lg["totals"]["strength_ready"] for lg in leagues),
            "leagues": leagues,
        },
        "morning_live": {
            "note": "finished fixtures; a snapshot counts from when it was both captured "
            "and stored",
            "absences_both_teams": _spread(_lead_hours(fixtures, absences)),
            "absences_at_decision": _at_decision(
                fixtures,
                absences,
                session.scalar(
                    select(func.min(TeamNewsSnapshot.captured_at)).where(
                        TeamNewsSnapshot.kind == TeamNewsKind.ABSENCES.value,
                        TeamNewsSnapshot.provider == provider,
                    )
                ),
                settings,
                set(
                    session.scalars(
                        select(Fixture.league_id)
                        .join(TeamNewsSnapshot, TeamNewsSnapshot.fixture_id == Fixture.id)
                        .where(
                            TeamNewsSnapshot.kind == TeamNewsKind.ABSENCES.value,
                            TeamNewsSnapshot.provider == provider,
                        )
                        .distinct()
                    )
                ),
            ),
            "lineups_both_teams": _spread(
                _lead_hours(fixtures, _first_captured(session, TeamNewsKind.LINEUP))
            ),
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    from edge_api.config import get_settings
    from edge_api.db.session import session_scope

    with session_scope() as session:
        settings = get_settings()
        report = readiness(session, settings.data_provider, settings)
    if args.out:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )
    return report


def summary(report: dict[str, Any]) -> dict[str, Any]:
    lt = report["line_up_time"]
    return {
        "strength_ready_verified_leagues": lt["strength_ready_verified_leagues"],
        "strength_ready_all_leagues": lt["strength_ready_all_leagues"],
        "leagues": [
            {
                "league": lg["league"],
                "verified": lg["verified"],
                **lg["totals"],
                "seasons": list(lg["seasons"]),
            }
            for lg in lt["leagues"]
        ],
        "morning_live": report["morning_live"],
    }
