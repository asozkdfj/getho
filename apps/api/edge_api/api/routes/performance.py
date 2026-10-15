from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.schemas import (
    CalibrationBinOut,
    DailyPickBacktestRowOut,
    DataStatusOut,
    EvaluationOut,
    LeagueEvaluationOut,
    LeagueModelMetricOut,
    LiveEvaluationOut,
    ModelMetricOut,
    PerformanceOut,
    SeasonMetricOut,
)
from edge_api.services.evaluations import latest_evaluation, live_evaluation
from edge_api.services.status import data_status

router = APIRouter(tags=["performance"])


def _metrics(section: dict[str, Any]) -> list[ModelMetricOut]:
    return [
        ModelMetricOut(
            name=name,
            n=section["n_matches"],
            log_loss=m["log_loss"]["mean"],
            log_loss_ci=[m["log_loss"]["ci_low"], m["log_loss"]["ci_high"]],
            brier=m["brier"]["mean"],
            rps=m["rps"]["mean"],
            accuracy=m["accuracy"],
            ece=m["ece"],
        )
        for name, m in section.get("models", {}).items()
    ]


def _league(entry: dict[str, Any]) -> LeagueEvaluationOut:
    models = entry.get("models", {})
    gain = entry.get("gain_vs_base_rate", {})
    return LeagueEvaluationOut(
        code=entry["code"],
        name=entry.get("name", entry["code"]),
        country=entry.get("country", ""),
        test_matches=entry.get("test_matches", 0),
        production=LeagueModelMetricOut(**models["production"]),
        base_rate=LeagueModelMetricOut(**models["base_rate"]),
        elo_only=LeagueModelMetricOut(**models["elo_only"]) if "elo_only" in models else None,
        gain_vs_base_rate=[
            gain.get("mean", 0.0),
            gain.get("ci_low", 0.0),
            gain.get("ci_high", 0.0),
        ],
        verified=bool(entry.get("verified")),
        data_warnings=entry.get("data_warnings", []),
    )


@router.get("/performance", response_model=PerformanceOut)
def performance(db: DbSession, settings: AppSettings) -> PerformanceOut:
    """Backtest results of the production model plus live scoring of stored predictions."""
    ev = latest_evaluation(db)
    evaluation = None
    if ev is not None:
        r = ev.report
        names = {lg.get("code"): lg.get("name") for lg in r.get("leagues") or []}
        test = r.get("test", {})
        prod = test.get("models", {}).get("production", {})
        evaluation = EvaluationOut(
            id=ev.id,
            created_at=ev.created_at,
            dataset=ev.dataset,
            license=(r.get("data") or {}).get("license"),
            n_matches=(r.get("data") or {}).get("n_matches", 0),
            seasons=(r.get("data") or {}).get("seasons", []),
            has_odds=bool((r.get("data") or {}).get("matches_with_odds")),
            split=r.get("split", {}),
            production_version=ev.model_version,
            validation=_metrics(r.get("validation", {})),
            test=_metrics(test),
            test_per_season=[
                SeasonMetricOut(season=s, **v) for s, v in prod.get("per_season", {}).items()
            ],
            calibration=[CalibrationBinOut(**b) for b in prod.get("calibration", [])],
            daily_picks=[
                DailyPickBacktestRowOut(**row)
                for row in (r.get("daily_pick_backtest") or {}).get("rows", [])
            ],
            daily_picks_leagues=[
                names.get(c, c) for c in (r.get("daily_pick_backtest") or {}).get("leagues", [])
            ],
            leagues=[_league(lg) for lg in r.get("leagues") or []],
            promotion_decisions={
                k: r[k]["reasons"] for k in ("promotion", "promotion_calibrated") if k in r
            },
        )
    return PerformanceOut(
        evaluation=evaluation,
        live=LiveEvaluationOut(**live_evaluation(db, settings.data_provider)),
    )


@router.get("/status/data", response_model=DataStatusOut)
def status_data(db: DbSession, settings: AppSettings, now: Now) -> DataStatusOut:
    """Freshness of collected data (monitoring)."""
    return DataStatusOut(**data_status(db, settings, now))
