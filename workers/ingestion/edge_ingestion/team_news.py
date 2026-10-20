"""Team news ingestion: absences, official line-ups and player minutes.

- absences (injured / suspended / doubtful) for fixtures in the next days
- official line-ups for fixtures about to start (polled until both are stored)
- player minutes of finished fixtures (tells regular starters from squad players)
  and, from the same response, team statistics: shots, shots on target, xG

Snapshots are append-only. A report identical to the latest stored one for
that team writes nothing; a changed report becomes a new row, including a
return to an earlier state (absent -> fit -> absent).

Absences have three states per team: players reported, "checked, none
reported" (an empty snapshot, only for fixtures the provider says it covered
in a league with injury coverage) and unknown (no snapshot). Not having data
never reads as "no absences".
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import (
    Fixture,
    FixtureStatus,
    League,
    MatchStatistic,
    PlayerAppearance,
    Team,
    TeamNewsKind,
    TeamNewsSnapshot,
)
from edge_api.services.leagues import scoped_league_ids
from edge_api.services.queries import latest_statistics
from edge_api.timeutil import ensure_utc
from edge_ingestion.providers.base import FootballDataProvider, PlayerRef, PostMatchReport

logger = logging.getLogger(__name__)

APPEARANCE_LOOKBACK = timedelta(days=120)


@dataclass(frozen=True, slots=True)
class TeamNewsResult:
    absence_snapshots: int = 0
    lineup_snapshots: int = 0
    appearances_inserted: int = 0
    statistics_inserted: int = 0


def content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _player(p: PlayerRef) -> dict[str, Any]:
    return {"player_id": p.provider_id, "name": p.name, "number": p.number, "position": p.position}


def _scoped(stmt: Select[Any], scope: frozenset[str] | None) -> Select[Any]:
    stmt = stmt.join(League, League.id == Fixture.league_id)
    return stmt if scope is None else stmt.where(League.provider_id.in_(scope))


def _team_ids(session: Session, provider: str) -> dict[str, int]:
    rows = session.execute(select(Team.provider_id, Team.id).where(Team.provider == provider))
    return {pid: tid for pid, tid in rows}


def _latest_hashes(
    session: Session, fixture_ids: set[int], kind: str
) -> dict[tuple[int, int], str]:
    ranked = (
        select(
            TeamNewsSnapshot.fixture_id,
            TeamNewsSnapshot.team_id,
            TeamNewsSnapshot.content_hash,
            func.row_number()
            .over(
                partition_by=(TeamNewsSnapshot.fixture_id, TeamNewsSnapshot.team_id),
                order_by=(TeamNewsSnapshot.captured_at.desc(), TeamNewsSnapshot.id.desc()),
            )
            .label("rn"),
        )
        .where(TeamNewsSnapshot.fixture_id.in_(fixture_ids), TeamNewsSnapshot.kind == kind)
        .subquery()
    )
    rows = session.execute(
        select(ranked.c.fixture_id, ranked.c.team_id, ranked.c.content_hash).where(ranked.c.rn == 1)
    )
    return {(fid, tid): h for fid, tid, h in rows}


def _insert_snapshots(session: Session, rows: list[dict[str, Any]]) -> int:
    """Insert the snapshots that differ from the latest stored one of their team."""
    if not rows:
        return 0
    written = 0
    for kind in {r["kind"] for r in rows}:
        of_kind = [r for r in rows if r["kind"] == kind]
        latest = _latest_hashes(session, {r["fixture_id"] for r in of_kind}, kind)
        new = [
            r for r in of_kind if latest.get((r["fixture_id"], r["team_id"])) != r["content_hash"]
        ]
        if new:
            session.execute(insert(TeamNewsSnapshot).values(new))
            written += len(new)
    return written


def _snapshot_row(
    fixture_id: int, team_id: int, provider: str, kind: str, payload: dict[str, Any], now: datetime
) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "team_id": team_id,
        "provider": provider,
        "kind": kind,
        "payload": payload,
        "content_hash": content_hash(payload),
        "captured_at": now,
    }


def ingest_absences(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    scope: frozenset[str] | None,
    horizon: timedelta,
) -> int:
    rows = session.execute(
        _scoped(
            select(
                Fixture.provider_id,
                Fixture.id,
                Fixture.kickoff_at,
                Fixture.home_team_id,
                Fixture.away_team_id,
                League.has_injuries,
            ),
            scope,
        ).where(
            Fixture.provider == provider.name,
            Fixture.status == FixtureStatus.SCHEDULED.value,
            Fixture.kickoff_at > now,
            Fixture.kickoff_at <= now + horizon,
        )
    ).all()
    if not rows:
        return 0
    fixture_ids = {r.provider_id: r.id for r in rows}
    teams = _team_ids(session, provider.name)
    report = provider.get_absence_report({r.provider_id: r.kickoff_at for r in rows})
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    # checked and covered: both teams get a snapshot, empty = none reported
    for r in rows:
        if r.provider_id in report.covered and r.has_injuries:
            grouped.setdefault((r.id, r.home_team_id), [])
            grouped.setdefault((r.id, r.away_team_id), [])
    for a in report.absences:
        fid, tid = fixture_ids.get(a.fixture_provider_id), teams.get(a.team_provider_id)
        if fid is None or tid is None:
            continue
        grouped[(fid, tid)].append({**_player(a.player), "status": a.status, "reason": a.reason})
    snapshots = [
        _snapshot_row(
            fid,
            tid,
            provider.name,
            TeamNewsKind.ABSENCES.value,
            {"players": sorted(players, key=lambda p: p["player_id"])},
            now,
        )
        for (fid, tid), players in grouped.items()
    ]
    return _insert_snapshots(session, snapshots)


def ingest_lineups(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    scope: frozenset[str] | None,
    window: timedelta,
) -> int:
    has_lineup = (
        select(func.count(TeamNewsSnapshot.team_id.distinct()))
        .where(
            TeamNewsSnapshot.fixture_id == Fixture.id,
            TeamNewsSnapshot.kind == TeamNewsKind.LINEUP.value,
        )
        .scalar_subquery()
    )
    rows = session.execute(
        _scoped(select(Fixture.provider_id, Fixture.id), scope).where(
            Fixture.provider == provider.name,
            Fixture.status.in_([FixtureStatus.SCHEDULED.value, FixtureStatus.LIVE.value]),
            Fixture.kickoff_at > now - timedelta(hours=2),
            Fixture.kickoff_at <= now + window,
            has_lineup < 2,
        )
    ).all()
    if not rows:
        return 0
    fixture_ids = {pid: fid for pid, fid in rows}
    teams = _team_ids(session, provider.name)
    snapshots = []
    for lu in provider.get_lineups(list(fixture_ids)):
        fid, tid = fixture_ids.get(lu.fixture_provider_id), teams.get(lu.team_provider_id)
        if fid is None or tid is None:
            continue
        payload = {
            "formation": lu.formation,
            "starters": [_player(p) for p in lu.starters],
            "substitutes": [_player(p) for p in lu.substitutes],
        }
        snapshots.append(
            _snapshot_row(fid, tid, provider.name, TeamNewsKind.LINEUP.value, payload, now)
        )
    return _insert_snapshots(session, snapshots)


def ingest_post_match(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    scope: frozenset[str] | None,
    limit: int,
    lookback: timedelta = APPEARANCE_LOOKBACK,
    source: str = "ingest",
) -> tuple[int, int]:
    """Player minutes and team statistics (shots, shots on target, xG) of
    finished fixtures still missing either (statistics of either team), from
    one fetch of their details.
    Returns (appearances inserted, statistics rows inserted)."""
    no_minutes = ~exists().where(PlayerAppearance.fixture_id == Fixture.id)

    def no_stats_for(team: Any) -> Any:
        return ~exists().where(
            MatchStatistic.fixture_id == Fixture.id, MatchStatistic.team_id == team
        )

    # each team on its own: one team's row stored must not end the retry for the other
    no_stats = no_stats_for(Fixture.home_team_id) | no_stats_for(Fixture.away_team_id)
    rows = session.execute(
        _scoped(select(Fixture.provider_id, Fixture.id), scope)
        .where(
            Fixture.provider == provider.name,
            Fixture.status == FixtureStatus.FINISHED.value,
            Fixture.kickoff_at < now,
            Fixture.kickoff_at >= now - lookback,
            no_minutes | no_stats,
        )
        .order_by(Fixture.kickoff_at.desc())
        .limit(max(limit, 0))
    ).all()
    if not rows:
        return 0, 0
    fixture_ids = {pid: fid for pid, fid in rows}
    teams = _team_ids(session, provider.name)
    report = provider.get_post_match(list(fixture_ids))
    values = []
    for ap in report.appearances:
        fid, tid = fixture_ids.get(ap.fixture_provider_id), teams.get(ap.team_provider_id)
        if fid is None or tid is None:
            continue
        values.append(
            {
                "fixture_id": fid,
                "team_id": tid,
                "provider": provider.name,
                "player_provider_id": ap.player.provider_id,
                "player_name": ap.player.name[:120],
                "started": ap.started,
                "minutes": ap.minutes,
            }
        )
    inserted = 0
    for i in range(0, len(values), 1000):
        stmt = (
            insert(PlayerAppearance)
            .values(values[i : i + 1000])
            .on_conflict_do_nothing(constraint="uq_player_appearances_fixture_player")
            .returning(PlayerAppearance.id)
        )
        inserted += len(session.execute(stmt).all())
    return inserted, _insert_statistics(session, provider.name, report, fixture_ids, teams, source)


def _insert_statistics(
    session: Session,
    provider: str,
    report: PostMatchReport,
    fixture_ids: dict[str, int],
    teams: dict[str, int],
    source: str,
) -> int:
    """Append each team's statistics when they differ from its latest stored row."""
    latest = {
        (o.fixture_id, o.team_id): (o.shots, o.shots_on_target, o.expected_goals)
        for o in latest_statistics(session, list(fixture_ids.values()))
    }
    rows = []
    for st in report.statistics:
        fid, tid = fixture_ids.get(st.fixture_provider_id), teams.get(st.team_provider_id)
        if fid is None or tid is None:
            continue
        xg = None if st.expected_goals is None else Decimal(str(round(st.expected_goals, 3)))
        if latest.get((fid, tid)) == (st.shots, st.shots_on_target, xg):
            continue
        rows.append(
            {
                "fixture_id": fid,
                "team_id": tid,
                "provider": provider,
                "shots": st.shots,
                "shots_on_target": st.shots_on_target,
                "expected_goals": xg,
                "source": source,
            }
        )
    if rows:
        session.execute(insert(MatchStatistic).values(rows))
    return len(rows)


def ingest_appearances(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    scope: frozenset[str] | None,
    limit: int,
    lookback: timedelta = APPEARANCE_LOOKBACK,
    source: str = "ingest",
) -> int:
    """Player minutes inserted (statistics are stored along the way)."""
    return ingest_post_match(
        session, provider, now=now, scope=scope, limit=limit, lookback=lookback, source=source
    )[0]


def ingest_team_news(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    settings: Settings,
    lineups_only: bool = False,
) -> TeamNewsResult:
    now = ensure_utc(now)
    scope = scoped_league_ids(session, provider.name, settings.team_news_leagues)
    lineups = ingest_lineups(
        session,
        provider,
        now=now,
        scope=scope,
        window=timedelta(minutes=settings.lineup_window_minutes),
    )
    if lineups_only:
        return TeamNewsResult(lineup_snapshots=lineups)
    absences = ingest_absences(
        session,
        provider,
        now=now,
        scope=scope,
        horizon=timedelta(hours=settings.absences_horizon_hours),
    )
    appearances, statistics = ingest_post_match(
        session, provider, now=now, scope=scope, limit=settings.appearances_per_run
    )
    result = TeamNewsResult(absences, lineups, appearances, statistics)
    logger.info("team news provider=%s %s", provider.name, result)
    return result
