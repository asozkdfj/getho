"""Private research view: collection health, shadow-v1 progress and live CLV.

Nothing here changes the model or the pick. During the shadow window only
counts and coverage are returned; its scores appear once the report is final.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Query

from edge_api.api.deps import AppSettings, DbSession, Now
from edge_api.schemas import (
    CollectionQualityOut,
    LiveClvFlagOut,
    LiveClvOut,
    ResearchDayOut,
    ResearchOut,
    ShadowProgressOut,
)
from edge_api.services.collection_quality import quality_report
from edge_api.services.live_clv import live_clv_report
from edge_api.services.picks import local_day
from edge_api.services.shadow import shadow_report
from edge_ml.shadow import EVALUATION_END, EVALUATION_START, MIN_SETTLED

router = APIRouter(tags=["research"])


def _collection(report: dict[str, Any], start: str, end: str) -> CollectionQualityOut:
    s = report["summary"]
    return CollectionQualityOut(
        start=start,
        end=end,
        expected_interval_minutes=report["expected_interval_minutes"],
        days_without_decision=s["days_without_decision"],
        days_with_failed_runs=s["days_with_failed_runs"],
        days_with_long_gaps=s["days_with_long_gaps"],
        days_with_shadow_errors=s["days_with_shadow_errors"],
        prediction_share=s["prediction_share"],
        odds_share=s["odds_share"],
        absences_known_share=s["absences_known_share"],
        days=[
            ResearchDayOut(
                day=d["day"],
                decided=d["decision"]["decided"],
                minutes_after_publish_hour=d["decision"]["minutes_after_publish_hour"],
                runs_success=d["runs"]["success"],
                runs_failed=d["runs"]["failed"],
                runs_expected=d["runs"]["expected"],
                longest_gap_hours=d["runs"]["longest_gap_hours"],
                fixtures_at_decision=d["fixtures_at_decision"],
                with_prediction=d["with_prediction"],
                with_odds=d["with_odds"],
                shadow_recorded=d["shadow"]["recorded"],
                shadow_error=d["shadow"]["error"],
            )
            for d in report["days"]
        ],
    )


def _shadow(report: dict[str, Any]) -> ShadowProgressOut:
    coverage = report.get("coverage_days") or {}
    timing = report.get("decision_timing") or {}
    final = report["status"] == "final"
    return ShadowProgressOut(
        protocol=report["protocol"],
        window_start=report["window"]["start"],
        window_end=report["window"]["end"],
        status=report["status"],
        recorded=report["recorded"],
        excluded=report["excluded"],
        settled=report["settled"],
        pending=report["pending"],
        not_played=report["not_played"],
        min_settled=MIN_SETTLED,
        days_with_records=coverage.get("with_records", 0),
        no_decision_days=coverage.get("no_decision", []),
        decision_delay_median_minutes=(timing.get("minutes_after_publish_hour") or {}).get(
            "median"
        ),
        # scores only once final: looking at them earlier could steer the protocol
        decisions={"decisions": report["decisions"], "metrics": report["metrics"]}
        if final
        else None,
    )


def _live_clv(report: dict[str, Any]) -> LiveClvOut:
    section = report["all"]
    partial = section.get("partial_by_day") or {}
    lags = section.get("closing_snapshot_minutes_before_kickoff") or {}
    return LiveClvOut(
        window_start=report["window"]["start"],
        window_end=report["window"]["end"],
        counts=report["counts"],
        analysed=section.get("n", 0),
        days=section.get("days", 0),
        b_model=partial.get("b_forecast"),
        b_model_ci=partial.get("b_forecast_ci95", [None, None]),
        b_base=partial.get("b_base"),
        signal=report["reading"]["signal"],
        share_moves_toward_model=section.get("share_moves_toward_model"),
        mean_abs_move=section.get("mean_abs_move"),
        closing_minutes_before_kickoff_median=lags.get("median"),
        large_gap=[LiveClvFlagOut(**f) for f in section.get("large_gap_clv", [])],
    )


@router.get("/research", response_model=ResearchOut)
def research(
    db: DbSession,
    settings: AppSettings,
    now: Now,
    days: int = Query(7, ge=1, le=31, description="Collection-quality days, ending today"),
) -> ResearchOut:
    provider = settings.data_provider
    today = local_day(now, settings).day
    start = today - timedelta(days=days - 1)
    interval = timedelta(seconds=float(os.getenv("PIPELINE_INTERVAL_SECONDS", "1800")))
    quality = quality_report(db, settings, start, today, now=now, interval=interval)
    shadow = shadow_report(db, provider, now=now, start=EVALUATION_START, end=EVALUATION_END)
    clv = live_clv_report(db, provider, now=now, start=EVALUATION_START, end=today)
    return ResearchOut(
        generated_at=now,
        provider=provider,
        is_demo=provider == "mock",
        collection=_collection(quality, start.isoformat(), today.isoformat()),
        shadow=_shadow(shadow),
        live_clv=_live_clv(clv),
    )
