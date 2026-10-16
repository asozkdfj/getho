"""Read-side queries. All datetimes in/out are UTC-aware."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edge_api.db.models import Fixture, League, OddsSnapshot, Prediction


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
    session: Session, fixture_ids: Sequence[int]
) -> dict[int, Prediction]:
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
        .where(Prediction.fixture_id.in_(fixture_ids))
        .subquery()
    )
    stmt = select(Prediction).join(ranked, ranked.c.id == Prediction.id).where(ranked.c.rn == 1)
    return {p.fixture_id: p for p in session.scalars(stmt).unique()}


def latest_prediction(session: Session, fixture_id: int) -> Prediction | None:
    return latest_predictions_by_fixture(session, [fixture_id]).get(fixture_id)
