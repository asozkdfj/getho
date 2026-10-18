"""What player information a 09:00 decision could actually have used.

For each pick day, at its decision time (the publish hour): every fixture of
the pick window still to kick off, and for each of its teams the absences
state (reported / checked, none / unknown), whether an official line-up was in
and whether the team had enough player minutes stored to tell regulars apart.
Only rows captured and stored by the decision time count, so a match played in
July but collected in October never counts for August.

Kickoff times are the current ones (a later reschedule moves a fixture between
days); that is noted in the report, not corrected.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import Fixture, PlayerAppearance, TeamNewsKind, TeamNewsSnapshot
from edge_api.services import queries
from edge_api.services.picks import local_day
from edge_api.services.team_news import MIN_MATCHES


def _latest_known(
    session: Session, fixture_ids: list[int], at: datetime
) -> dict[tuple[int, int, str], dict[str, Any]]:
    ranked = (
        select(
            TeamNewsSnapshot.fixture_id,
            TeamNewsSnapshot.team_id,
            TeamNewsSnapshot.kind,
            TeamNewsSnapshot.payload,
            func.row_number()
            .over(
                partition_by=(
                    TeamNewsSnapshot.fixture_id,
                    TeamNewsSnapshot.team_id,
                    TeamNewsSnapshot.kind,
                ),
                order_by=(TeamNewsSnapshot.captured_at.desc(), TeamNewsSnapshot.id.desc()),
            )
            .label("rn"),
        )
        .where(
            TeamNewsSnapshot.fixture_id.in_(fixture_ids),
            TeamNewsSnapshot.captured_at <= at,
            TeamNewsSnapshot.created_at <= at,
        )
        .subquery()
    )
    rows = session.execute(
        select(ranked.c.fixture_id, ranked.c.team_id, ranked.c.kind, ranked.c.payload).where(
            ranked.c.rn == 1
        )
    )
    return {(fid, tid, kind): payload for fid, tid, kind, payload in rows}


def _matches_with_minutes(session: Session, team_ids: set[int], at: datetime) -> dict[int, int]:
    rows = session.execute(
        select(PlayerAppearance.team_id, func.count(PlayerAppearance.fixture_id.distinct()))
        .join(Fixture, Fixture.id == PlayerAppearance.fixture_id)
        .where(
            PlayerAppearance.team_id.in_(team_ids),
            Fixture.kickoff_at < at,
            PlayerAppearance.created_at <= at,
        )
        .group_by(PlayerAppearance.team_id)
    )
    return {tid: n for tid, n in rows}


def coverage_on(session: Session, settings: Settings, day: date) -> dict[str, Any]:
    zone = ZoneInfo(settings.pick_tz)
    ld = local_day(datetime.combine(day, time(settings.pick_publish_hour), tzinfo=zone), settings)
    at = ld.publish_at
    fixtures = [
        f
        for f in queries.fixtures_between(session, ld.start_utc, ld.end_utc, settings.data_provider)
        if f.kickoff_at > at
    ]
    ids = [f.id for f in fixtures]
    known = _latest_known(session, ids, at) if ids else {}
    teams = {t for f in fixtures for t in (f.home_team_id, f.away_team_id)}
    minutes = _matches_with_minutes(session, teams, at) if teams else {}
    absences: Counter[str] = Counter()
    lineups = regulars = 0
    for f in fixtures:
        for team in (f.home_team_id, f.away_team_id):
            report = known.get((f.id, team, TeamNewsKind.ABSENCES.value))
            if report is None:
                absences["unknown"] += 1
            else:
                absences["reported" if report.get("players") else "none_reported"] += 1
            lineups += (f.id, team, TeamNewsKind.LINEUP.value) in known
            regulars += minutes.get(team, 0) >= MIN_MATCHES
    return {
        "day": day.isoformat(),
        "decision_at": at.isoformat(),
        "fixtures": len(fixtures),
        "team_slots": 2 * len(fixtures),
        "absences": {k: absences.get(k, 0) for k in ("reported", "none_reported", "unknown")},
        "lineups_in": lineups,
        "regulars_known": regulars,
    }


def coverage_report(session: Session, settings: Settings, start: date, end: date) -> dict[str, Any]:
    days = [
        coverage_on(session, settings, start + timedelta(days=i))
        for i in range((end - start).days + 1)
    ]
    slots = sum(d["team_slots"] for d in days)
    totals = {
        "fixtures": sum(d["fixtures"] for d in days),
        "team_slots": slots,
        "absences": {
            k: sum(d["absences"][k] for d in days) for k in ("reported", "none_reported", "unknown")
        },
        "lineups_in": sum(d["lineups_in"] for d in days),
        "regulars_known": sum(d["regulars_known"] for d in days),
    }
    return {
        "provider": settings.data_provider,
        "decision_hour": f"{settings.pick_publish_hour:02d}:00 {settings.pick_tz}",
        "note": "only rows captured and stored by each decision time; kickoffs are current",
        "totals": totals,
        "days": days,
    }
