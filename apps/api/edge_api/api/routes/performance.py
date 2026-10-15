from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.schemas import (
    CalibrationBinOut,
    DailyPickBacktestRowOut,
    DataStatusOut,
    EvaluationOut,
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


@router.get("/performance", response_model=PerformanceOut)
def performance(db: DbSession, settings: AppSettings) -> PerformanceOut:
    """Backtest results of the production model plus live scoring of stored predictions."""
    ev = latest_evaluation(db)
    evaluation = None
    if ev is not None:
        r = ev.report
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
