"""Team news read side: line-ups, absences and which regular starters are missing.

Every read can be limited to what was known at a moment (``as_of``): snapshots
captured and stored by then, and player minutes stored by then (a match played
in July but first collected in October was not known in August).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edge_api.db.models import Fixture, PlayerAppearance, Team, TeamNewsKind, TeamNewsSnapshot
from edge_api.schemas import (
    AbsenceOut,
    LineupPlayerOut,
    MissingRegularOut,
    TeamNewsOut,
    TeamNewsSideOut,
)

RECENT_MATCHES = 10  # matches used to find a team's regular starters
REGULARS = 11
MIN_MATCHES = 3  # fewer than this and "regular" means little


def regular_players(
    session: Session, team_id: int, before: datetime, known_by: datetime | None = None
) -> tuple[list[tuple[str, str]], int]:
    """(player_id, name) of the team's most used players in its recent matches
    before ``before``, counting only minutes stored by ``known_by``."""
    where = [PlayerAppearance.team_id == team_id, Fixture.kickoff_at < before]
    if known_by is not None:
        where.append(PlayerAppearance.created_at <= known_by)
    recent = (
        select(Fixture.id)
        .join(PlayerAppearance, PlayerAppearance.fixture_id == Fixture.id)
        .where(*where)
        .group_by(Fixture.id, Fixture.kickoff_at)
        .order_by(Fixture.kickoff_at.desc())
        .limit(RECENT_MATCHES)
        .subquery()
    )
    rows = session.execute(
        select(
            PlayerAppearance.player_provider_id,
            func.max(PlayerAppearance.player_name),
            func.sum(PlayerAppearance.minutes).label("minutes"),
        )
        .where(PlayerAppearance.team_id == team_id, PlayerAppearance.fixture_id.in_(select(recent)))
        .group_by(PlayerAppearance.player_provider_id)
        .order_by(func.sum(PlayerAppearance.minutes).desc(), PlayerAppearance.player_provider_id)
        .limit(REGULARS)
    ).all()
    n_matches = session.scalar(select(func.count()).select_from(recent)) or 0
    return [(pid, name) for pid, name, _ in rows], n_matches


def latest_snapshots(
    session: Session, fixture_id: int, kind: TeamNewsKind, as_of: datetime | None = None
) -> dict[int, TeamNewsSnapshot]:
    """Latest snapshot per team; with ``as_of`` only those captured and stored by then."""
    where = [TeamNewsSnapshot.fixture_id == fixture_id, TeamNewsSnapshot.kind == kind.value]
    if as_of is not None:
        where += [TeamNewsSnapshot.captured_at <= as_of, TeamNewsSnapshot.created_at <= as_of]
    snaps = session.scalars(
        select(TeamNewsSnapshot)
        .where(*where)
        .order_by(TeamNewsSnapshot.captured_at, TeamNewsSnapshot.id)
    ).all()
    latest: dict[int, TeamNewsSnapshot] = {}
    for snap in snaps:  # ascending: the last one per team wins
        latest[snap.team_id] = snap
    return latest


def absences_status(snapshot: TeamNewsSnapshot | None) -> str:
    """reported | none_reported (checked, empty) | unknown (never checked)."""
    if snapshot is None:
        return "unknown"
    return "reported" if snapshot.payload.get("players") else "none_reported"


def _side(
    session: Session,
    fixture: Fixture,
    team: Team,
    lineup: TeamNewsSnapshot | None,
    absences: TeamNewsSnapshot | None,
    as_of: datetime | None,
) -> TeamNewsSideOut:
    regulars, n_matches = regular_players(session, team.id, fixture.kickoff_at, as_of)
    known = n_matches >= MIN_MATCHES
    regular_ids = {pid for pid, _ in regulars} if known else set()
    absent: list[dict[str, Any]] = list((absences.payload if absences else {}).get("players", []))
    reasons = {a["player_id"]: a.get("reason") for a in absent}
    starters = list((lineup.payload if lineup else {}).get("starters", []))
    if lineup is not None:
        in_xi = {p["player_id"] for p in starters}
        missing = [(pid, name) for pid, name in regulars if pid not in in_xi] if known else []
    else:
        out_ids = {a["player_id"] for a in absent if a.get("status") == "out"}
        missing = [(pid, name) for pid, name in regulars if pid in out_ids] if known else []
    return TeamNewsSideOut(
        team_id=team.id,
        team_name=team.name,
        formation=(lineup.payload.get("formation") if lineup else None),
        starters=[
            LineupPlayerOut(
                player_id=p["player_id"],
                name=p["name"],
                number=p.get("number"),
                position=p.get("position"),
                regular=p["player_id"] in regular_ids,
            )
            for p in starters
        ],
        lineup_captured_at=lineup.captured_at if lineup else None,
        absences=[
            AbsenceOut(
                player_id=a["player_id"],
                name=a["name"],
                status=a.get("status", "doubtful"),
                reason=a.get("reason"),
                regular=a["player_id"] in regular_ids,
            )
            for a in absent
        ],
        absences_captured_at=absences.captured_at if absences else None,
        absences_status=absences_status(absences),
        missing_regulars=[
            MissingRegularOut(player_id=pid, name=name, reason=reasons.get(pid))
            for pid, name in missing
        ],
        regulars_known=known,
        recent_matches=n_matches,
    )


def team_news(
    session: Session, fixture: Fixture, as_of: datetime | None = None
) -> TeamNewsOut | None:
    lineups = latest_snapshots(session, fixture.id, TeamNewsKind.LINEUP, as_of)
    absences = latest_snapshots(session, fixture.id, TeamNewsKind.ABSENCES, as_of)
    minutes = [PlayerAppearance.team_id.in_([fixture.home_team_id, fixture.away_team_id])]
    if as_of is not None:
        minutes.append(PlayerAppearance.created_at <= as_of)
    has_minutes = session.scalar(select(func.count()).select_from(PlayerAppearance).where(*minutes))
    if not lineups and not absences and not has_minutes:
        return None
    sides = [
        _side(session, fixture, team, lineups.get(team.id), absences.get(team.id), as_of)
        for team in (fixture.home_team, fixture.away_team)
    ]
    return TeamNewsOut(
        lineups_announced=fixture.home_team_id in lineups and fixture.away_team_id in lineups,
        home=sides[0],
        away=sides[1],
    )


def fixtures_with_lineups(session: Session, fixture_ids: Sequence[int]) -> set[int]:
    """Fixtures for which both teams' official line-ups are stored."""
    if not fixture_ids:
        return set()
    rows = session.execute(
        select(TeamNewsSnapshot.fixture_id, func.count(TeamNewsSnapshot.team_id.distinct()))
        .where(
            TeamNewsSnapshot.fixture_id.in_(fixture_ids),
            TeamNewsSnapshot.kind == TeamNewsKind.LINEUP.value,
        )
        .group_by(TeamNewsSnapshot.fixture_id)
    ).all()
    counts: dict[int, int] = defaultdict(int, {fid: n for fid, n in rows})
    return {fid for fid in fixture_ids if counts[fid] >= 2}
