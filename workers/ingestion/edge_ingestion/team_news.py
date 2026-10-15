"""Team news ingestion: absences, official line-ups and player minutes.

- absences (injured / suspended / doubtful) for fixtures in the next days
- official line-ups for fixtures about to start (polled until both are stored)
- player minutes of finished fixtures (tells regular starters from squad players)

Snapshots are append-only and keyed by a content hash, so polling the same
report again writes nothing; a changed report becomes a new row.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import (
    Fixture,
    FixtureStatus,
    League,
    PlayerAppearance,
    Team,
    TeamNewsKind,
    TeamNewsSnapshot,
)
from edge_api.services.leagues import scoped_league_ids
from edge_api.timeutil import ensure_utc
from edge_ingestion.providers.base import FootballDataProvider, PlayerRef

logger = logging.getLogger(__name__)

APPEARANCE_LOOKBACK = timedelta(days=120)


@dataclass(frozen=True, slots=True)
class TeamNewsResult:
    absence_snapshots: int = 0
    lineup_snapshots: int = 0
    appearances_inserted: int = 0


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


def _insert_snapshots(session: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = (
        insert(TeamNewsSnapshot)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_team_news_snapshots_content_key")
        .returning(TeamNewsSnapshot.id)
    )
    return len(session.execute(stmt).all())


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
        _scoped(select(Fixture.provider_id, Fixture.id, Fixture.kickoff_at), scope).where(
            Fixture.provider == provider.name,
            Fixture.status == FixtureStatus.SCHEDULED.value,
            Fixture.kickoff_at > now,
            Fixture.kickoff_at <= now + horizon,
        )
    ).all()
    if not rows:
        return 0
    fixture_ids = {pid: fid for pid, fid, _ in rows}
    teams = _team_ids(session, provider.name)
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for a in provider.get_absences({pid: kickoff for pid, _, kickoff in rows}):
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


def ingest_appearances(
    session: Session,
    provider: FootballDataProvider,
    *,
    now: datetime,
    scope: frozenset[str] | None,
    limit: int,
) -> int:
    missing = ~exists().where(PlayerAppearance.fixture_id == Fixture.id)
    rows = session.execute(
        _scoped(select(Fixture.provider_id, Fixture.id), scope)
        .where(
            Fixture.provider == provider.name,
            Fixture.status == FixtureStatus.FINISHED.value,
            Fixture.kickoff_at < now,
            Fixture.kickoff_at >= now - APPEARANCE_LOOKBACK,
            missing,
        )
        .order_by(Fixture.kickoff_at.desc())
        .limit(max(limit, 0))
    ).all()
    if not rows:
        return 0
    fixture_ids = {pid: fid for pid, fid in rows}
    teams = _team_ids(session, provider.name)
    values = []
    for ap in provider.get_appearances(list(fixture_ids)):
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
    return inserted


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
    appearances = ingest_appearances(
        session, provider, now=now, scope=scope, limit=settings.appearances_per_run
    )
    result = TeamNewsResult(absences, lineups, appearances)
    logger.info("team news provider=%s %s", provider.name, result)
    return result
