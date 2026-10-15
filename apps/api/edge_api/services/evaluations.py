"""Stored backtest reports and live (paper) evaluation of real predictions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edge_api.db.models import Fixture, FixtureStatus, ModelEvaluation
from edge_api.services import queries
from edge_api.services.analysis import market_view
from edge_ml.metrics import bootstrap_mean_ci, brier_per_match, log_loss_per_match
from edge_ml.model import FEATURE_SET, MODEL_NAME, MODEL_VERSION

# Committed real-data backtest (see docs/MODEL_EVALUATION.md)
DEFAULT_REPORT = Path(__file__).resolve().parents[4] / "ml/reports/backtest-openfootball.json"


def import_report(session: Session, path: Path = DEFAULT_REPORT) -> int | None:
    """Store a backtest report once (dedup by content hash). Returns the row id."""
    if not path.exists():
        return None
    raw = path.read_bytes()
    report = json.loads(raw)
    prod = report.get("production", {})
    stmt = (
        insert(ModelEvaluation)
        .values(
            model_name=MODEL_NAME,
            model_version=prod.get("version", MODEL_VERSION),
            feature_set=prod.get("feature_set", FEATURE_SET),
            dataset=(report.get("data") or {}).get("name", path.name),
            report=report,
            report_sha256=hashlib.sha256(raw).hexdigest(),
        )
        .on_conflict_do_nothing(constraint="uq_model_evaluations_report_sha256")
        .returning(ModelEvaluation.id)
    )
    return session.execute(stmt).scalar_one_or_none()


def latest_evaluation(session: Session) -> ModelEvaluation | None:
    return session.scalars(
        select(ModelEvaluation)
        .order_by(ModelEvaluation.created_at.desc(), ModelEvaluation.id.desc())
        .limit(1)
    ).first()


def live_evaluation(session: Session, provider: str) -> dict[str, Any]:
    """Score stored pre-match predictions of finished matches: model vs market.

    Uses each fixture's latest prediction (all predictions are pre-kickoff) and
    the odds snapshot that prediction referenced, so both sides saw the same
    information time.
    """
    finished = (
        session.scalars(
            select(Fixture).where(
                Fixture.provider == provider,
                Fixture.status == FixtureStatus.FINISHED.value,
                Fixture.home_score.is_not(None),
            )
        )
        .unique()
        .all()
    )
    preds = queries.latest_predictions_by_fixture(session, [f.id for f in finished])
    model_rows, market_rows, outcomes = [], [], []
    for f in finished:
        p = preds.get(f.id)
        if p is None:
            continue
        model_rows.append((p.probability_home, p.probability_draw, p.probability_away))
        market_rows.append(market_view(p.odds_snapshot).fair.as_tuple())
        hs, as_ = f.home_score, f.away_score
        outcomes.append(0 if hs > as_ else 1 if hs == as_ else 2)  # type: ignore[operator]
    n = len(outcomes)
    out: dict[str, Any] = {"provider": provider, "n_matches": n, "is_demo": provider == "mock"}
    if n == 0:
        return out
    y = np.array(outcomes)
    for name, rows in (("model", model_rows), ("market", market_rows)):
        p = np.array(rows)
        ll, br = log_loss_per_match(p, y), brier_per_match(p, y)
        lo, hi = bootstrap_mean_ci(ll, n_resamples=1000) if n >= 2 else (float(ll[0]),) * 2
        out[name] = {
            "log_loss": float(ll.mean()),
            "log_loss_ci": [lo, hi],
            "brier": float(br.mean()),
        }
    return out
