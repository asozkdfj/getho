from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.catalog import REGION_KO, REGIONS, featured_rank, region_of
from edge_api.db.models import Fixture, League, Prediction
from edge_api.schemas import (
    CountryGroupOut,
    ErrorOut,
    LeagueListOut,
    LeagueSummaryOut,
    RegionGroupOut,
)
from edge_api.services.leagues import league_ref, verified_league_ids

router = APIRouter(prefix="/leagues", tags=["leagues"])


def _counts(
    db: DbSession, provider: str, start: datetime, end: datetime
) -> dict[int, tuple[int, int]]:
    predicted = select(Prediction.fixture_id).distinct().subquery()
    rows = db.execute(
        select(
            Fixture.league_id,
            func.count(Fixture.id),
            func.count(predicted.c.fixture_id),
        )
        .outerjoin(predicted, predicted.c.fixture_id == Fixture.id)
        .where(Fixture.provider == provider, Fixture.kickoff_at >= start, Fixture.kickoff_at < end)
        .group_by(Fixture.league_id)
    ).all()
    return {league_id: (n, p) for league_id, n, p in rows}


def _summary(league: League, counts: tuple[int, int], verified: frozenset[str]) -> LeagueSummaryOut:
    return LeagueSummaryOut(
        **league_ref(league, verified).model_dump(),
        current_season=league.current_season,
        upcoming_count=counts[0],
        predicted_count=counts[1],
    )


def _order(summary: LeagueSummaryOut, league: League) -> tuple[int, int, str]:
    return (
        featured_rank(league.provider, league.provider_id) or 10_000,
        -summary.upcoming_count,
        summary.name,
    )


@router.get("", response_model=LeagueListOut)
def list_leagues(
    db: DbSession,
    settings: AppSettings,
    now: Now,
    days: Annotated[int, Query(ge=1, le=14, description="Window for fixture counts")] = 7,
    active_only: Annotated[
        bool, Query(description="Only leagues with fixtures in the window")
    ] = True,
) -> LeagueListOut:
    """League catalogue grouped by region and country, with upcoming fixture counts."""
    start = now.astimezone(UTC) - timedelta(hours=3)  # keep matches in progress
    end = now.astimezone(UTC) + timedelta(days=days)
    counts = _counts(db, settings.data_provider, start, end)
    verified = verified_league_ids(db, settings.data_provider)
    leagues = db.scalars(select(League).where(League.provider == settings.data_provider)).all()

    summaries: list[tuple[LeagueSummaryOut, League]] = []
    for league in leagues:
        c = counts.get(league.id, (0, 0))
        if active_only and c[0] == 0:
            continue
        summaries.append((_summary(league, c, verified), league))
    summaries.sort(key=lambda pair: _order(*pair))

    tree: dict[str, dict[str, list[tuple[LeagueSummaryOut, League]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for summary, league in summaries:
        tree[region_of(league.country)][league.country].append((summary, league))

    def country_order(pairs: list[tuple[LeagueSummaryOut, League]]) -> tuple[int, int, str]:
        # countries with featured leagues first, then by number of matches
        best = min(_order(s, lg)[0] for s, lg in pairs)
        return best, -sum(s.upcoming_count for s, _ in pairs), pairs[0][0].country_ko

    regions = []
    for region in (*REGIONS, "other"):
        if region not in tree:
            continue
        countries = [
            CountryGroupOut(
                country=country,
                country_ko=pairs[0][0].country_ko,
                flag_url=pairs[0][0].flag_url,
                leagues=[s for s, _ in pairs],
            )
            for country, pairs in sorted(tree[region].items(), key=lambda kv: country_order(kv[1]))
        ]
        regions.append(
            RegionGroupOut(region=region, region_ko=REGION_KO[region], countries=countries)
        )
    return LeagueListOut(
        data_provider=settings.data_provider,
        days=days,
        total_leagues=len(summaries),
        featured=[s for s, _ in summaries if s.featured],
        regions=regions,
    )


@router.get("/{league_id}", response_model=LeagueSummaryOut, responses={404: {"model": ErrorOut}})
def get_league(league_id: int, db: DbSession, settings: AppSettings, now: Now) -> LeagueSummaryOut:
    league = db.get(League, league_id)
    if league is None or league.provider != settings.data_provider:
        raise HTTPException(status_code=404, detail="league not found")
    start, end = now.astimezone(UTC) - timedelta(hours=3), now.astimezone(UTC) + timedelta(days=7)
    counts = _counts(db, settings.data_provider, start, end).get(league.id, (0, 0))
    return _summary(league, counts, verified_league_ids(db, settings.data_provider))
