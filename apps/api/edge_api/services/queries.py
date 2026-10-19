"""Read-side queries. All datetimes in/out are UTC-aware."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edge_api.db.models import (
    Fixture,
    FixtureObservation,
    FixtureStatus,
    League,
    MatchStatistic,
    OddsSnapshot,
    Prediction,
)


def fixtures_between(
    session: Session,
    start: datetime,
    end: datetime,
    provider: str,
    *,
    league_id: int | None = None,
    country: str | None = None,
) -> Sequence[Fixture]:
    """Fixtures of ONE data provider (mock and real data are never mixed)."""
    stmt = select(Fixture).where(
        Fixture.provider == provider, Fixture.kickoff_at >= start, Fixture.kickoff_at < end
    )
    if league_id is not None:
        stmt = stmt.where(Fixture.league_id == league_id)
    if country is not None:
        stmt = stmt.join(League, League.id == Fixture.league_id).where(League.country == country)
    return session.scalars(stmt.order_by(Fixture.kickoff_at, Fixture.id)).unique().all()


def get_fixture(session: Session, fixture_id: int) -> Fixture | None:
    return session.get(Fixture, fixture_id)


def latest_odds_by_fixture(
    session: Session, fixture_ids: Sequence[int], bookmaker: str
) -> dict[int, OddsSnapshot]:
    if not fixture_ids:
        return {}
    ranked = (
        select(
            OddsSnapshot.id,
            func.row_number()
            .over(
                partition_by=OddsSnapshot.fixture_id,
                order_by=(OddsSnapshot.captured_at.desc(), OddsSnapshot.id.desc()),
            )
            .label("rn"),
        )
        .where(OddsSnapshot.fixture_id.in_(fixture_ids), OddsSnapshot.bookmaker == bookmaker)
        .subquery()
    )
    stmt = select(OddsSnapshot).join(ranked, ranked.c.id == OddsSnapshot.id).where(ranked.c.rn == 1)
    return {o.fixture_id: o for o in session.scalars(stmt)}


def odds_history(session: Session, fixture_id: int, bookmaker: str) -> Sequence[OddsSnapshot]:
    stmt = (
        select(OddsSnapshot)
        .where(OddsSnapshot.fixture_id == fixture_id, OddsSnapshot.bookmaker == bookmaker)
        .order_by(OddsSnapshot.captured_at, OddsSnapshot.id)
    )
    return session.scalars(stmt).all()


def latest_predictions_by_fixture(
    session: Session, fixture_ids: Sequence[int], as_of: datetime | None = None
) -> dict[int, Prediction]:
    """Newest prediction per fixture. With ``as_of``, only predictions whose
    inputs were all known by then (a decision must not see later data)."""
    if not fixture_ids:
        return {}
    where = [Prediction.fixture_id.in_(fixture_ids)]
    if as_of is not None:
        where.append(Prediction.input_data_as_of <= as_of)
    ranked = (
        select(
            Prediction.id,
            func.row_number()
            .over(
                partition_by=Prediction.fixture_id,
                order_by=(Prediction.created_at.desc(), Prediction.id.desc()),
            )
            .label("rn"),
        )
        .where(*where)
        .subquery()
    )
    stmt = select(Prediction).join(ranked, ranked.c.id == Prediction.id).where(ranked.c.rn == 1)
    return {p.fixture_id: p for p in session.scalars(stmt).unique()}


def latest_prediction(session: Session, fixture_id: int) -> Prediction | None:
    return latest_predictions_by_fixture(session, [fixture_id]).get(fixture_id)


def predictions_before_kickoff(
    session: Session, fixture_ids: Sequence[int]
) -> dict[int, Prediction]:
    """Newest prediction per fixture that existed before its kickoff: built only
    from pre-kickoff data AND stored before kickoff (what the service could show
    going into the match). A re-analysis made after kickoff is never picked."""
    if not fixture_ids:
        return {}
    ranked = (
        select(
            Prediction.id,
            func.row_number()
            .over(
                partition_by=Prediction.fixture_id,
                order_by=(Prediction.created_at.desc(), Prediction.id.desc()),
            )
            .label("rn"),
        )
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .where(
            Prediction.fixture_id.in_(fixture_ids),
            Prediction.input_data_as_of <= Fixture.kickoff_at,
            Prediction.created_at <= Fixture.kickoff_at,
        )
        .subquery()
    )
    stmt = select(Prediction).join(ranked, ranked.c.id == Prediction.id).where(ranked.c.rn == 1)
    return {p.fixture_id: p for p in session.scalars(stmt).unique()}


def latest_observations(
    session: Session, fixture_ids: Sequence[int]
) -> Sequence[FixtureObservation]:
    """The newest stored observation of each fixture."""
    if not fixture_ids:
        return []
    ranked = (
        select(
            FixtureObservation.id,
            func.row_number()
            .over(
                partition_by=FixtureObservation.fixture_id,
                order_by=(FixtureObservation.created_at.desc(), FixtureObservation.id.desc()),
            )
            .label("rn"),
        )
        .where(FixtureObservation.fixture_id.in_(fixture_ids))
        .subquery()
    )
    return session.scalars(
        select(FixtureObservation)
        .join(ranked, ranked.c.id == FixtureObservation.id)
        .where(ranked.c.rn == 1)
    ).all()


def result_first_observed(session: Session, fixture_ids: Sequence[int]) -> dict[int, datetime]:
    """When a final result was first stored for each fixture (the earliest
    moment any decision could have used it). Fixtures without one are absent."""
    if not fixture_ids:
        return {}
    rows = session.execute(
        select(FixtureObservation.fixture_id, func.min(FixtureObservation.created_at))
        .where(
            FixtureObservation.fixture_id.in_(fixture_ids),
            FixtureObservation.status == FixtureStatus.FINISHED.value,
            FixtureObservation.home_score.is_not(None),
            FixtureObservation.away_score.is_not(None),
        )
        .group_by(FixtureObservation.fixture_id)
    ).all()
    return {fid: at for fid, at in rows}


def result_history(session: Session, fixture_id: int) -> list[dict[str, object]]:
    """Every stored state of a fixture in order, with whether the final score
    differs from the first one that was recorded (a correction)."""
    rows = session.scalars(
        select(FixtureObservation)
        .where(FixtureObservation.fixture_id == fixture_id)
        .order_by(FixtureObservation.created_at, FixtureObservation.id)
    ).all()
    first_final: tuple[int | None, int | None] | None = None
    out: list[dict[str, object]] = []
    for o in rows:
        score = (o.home_score, o.away_score)
        final = o.status == FixtureStatus.FINISHED.value and None not in score
        if final and first_final is None:
            first_final = score
        out.append(
            {
                "observed_at": o.created_at,
                "source": o.source,
                "status": o.status,
                "kickoff_at": o.kickoff_at,
                "home_score": o.home_score,
                "away_score": o.away_score,
                "corrects_result": final and first_final is not None and score != first_final,
            }
        )
    return out


def latest_statistics(
    session: Session, fixture_ids: Sequence[int], as_of: datetime | None = None
) -> Sequence[MatchStatistic]:
    """Each team's latest post-match statistics row; with ``as_of`` only rows
    stored by then (what a decision at that moment could have used)."""
    if not fixture_ids:
        return []
    where = [MatchStatistic.fixture_id.in_(fixture_ids)]
    if as_of is not None:
        where.append(MatchStatistic.created_at <= as_of)
    ranked = (
        select(
            MatchStatistic.id,
            func.row_number()
            .over(
                partition_by=(MatchStatistic.fixture_id, MatchStatistic.team_id),
                order_by=(MatchStatistic.created_at.desc(), MatchStatistic.id.desc()),
            )
            .label("rn"),
        )
        .where(*where)
        .subquery()
    )
    return session.scalars(
        select(MatchStatistic)
        .join(ranked, ranked.c.id == MatchStatistic.id)
        .where(ranked.c.rn == 1)
    ).all()
