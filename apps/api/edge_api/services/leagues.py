"""League catalogue read side: categorisation and per-league flags."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from edge_api.catalog import country_ko, featured_rank, region_of
from edge_api.db.models import League, LeagueType, ModelEvaluation
from edge_api.schemas import LeagueRefOut
from edge_ml.model import FEATURE_SET, MODEL_VERSION


def verified_league_ids(session: Session, provider: str) -> frozenset[str]:
    """Provider league ids whose accuracy the latest backtest of the current model
    measured on real results (and found better than the base-rate baseline)."""
    ev = session.scalars(
        select(ModelEvaluation)
        .where(
            ModelEvaluation.model_version == MODEL_VERSION,
            ModelEvaluation.feature_set == FEATURE_SET,
        )
        .order_by(ModelEvaluation.created_at.desc(), ModelEvaluation.id.desc())
        .limit(1)
    ).first()
    if ev is None:
        return frozenset()
    return frozenset(
        str(entry["provider_ids"][provider])
        for entry in _report_leagues(ev.report)
        if entry.get("verified") and provider in (entry.get("provider_ids") or {})
    )


def _report_leagues(report: dict[str, Any]) -> Iterable[dict[str, Any]]:
    leagues = report.get("leagues")
    return leagues if isinstance(leagues, list) else []


def is_predicted(league: League) -> bool:
    return league.type == LeagueType.LEAGUE.value and league.results_synced_at is not None


def league_ref(league: League, verified: frozenset[str]) -> LeagueRefOut:
    return LeagueRefOut(
        id=league.id,
        name=league.name,
        country=league.country,
        country_ko=country_ko(league.country),
        region=region_of(league.country),  # type: ignore[arg-type]
        type=league.type,  # type: ignore[arg-type]
        logo_url=league.logo_url,
        flag_url=league.flag_url,
        featured=featured_rank(league.provider, league.provider_id) is not None,
        predicted=is_predicted(league),
        verified=league.provider_id in verified,
    )
