"""`edge backtest-draws` - does a rolling draw-rate recalibration help?

Pre-registered protocol (committed before the first run; do not edit after results):

Idea     QA found the recent loss increase came mostly from a higher share of
         draws. Candidate: scale the production draw probability by
             k = 1 + w * (observed draws / predicted draws - 1)
         over the league's last N matches whose results were known when the
         model was fitted (kickoff + 3 h before the fit time), clamped to
         [0.80, 1.25], then renormalise the three probabilities.
Variants draw_recal_380_half   N = 380, w = 0.5
         draw_recal_760_half   N = 760, w = 0.5
         draw_recal_380_full   N = 380, w = 1.0
         Fewer than N earlier predicted matches -> k = 1 (no change).
Data     The same 9 pooled leagues and production predictions as
         `edge backtest-standings` (weekly refit, 3 h result delay).
Windows  2019-20 warm-up (only feeds the rolling window), 2020-21..2022-23
         validation (choose one variant: lowest pooled log loss),
         2023-24..2025-26 follow-up.
Gate     validation gain >= 0.001 AND follow-up gain >= 0.002 AND weekly
         paired 95% CI upper bound < 0 AND Brier not worse (pooled).
         Passing is a research result only: no automatic deployment.
"""

from __future__ import annotations

import argparse
import bisect
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from edge_ingestion.feature_experiment import (
    RESULT_DELAY,
    Experiment,
    Row,
    gate,
    production_rows,
    write_predictions,
)
from edge_ingestion.history import openfootball
from edge_ingestion.standings_backtest import FIRST, FOLLOW_UP, LAST, LEAGUES, VALIDATION, WARMUP
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams

logger = logging.getLogger(__name__)

K_MIN, K_MAX = 0.80, 1.25
VARIANTS: dict[str, tuple[int, float]] = {
    "draw_recal_380_half": (380, 0.5),
    "draw_recal_760_half": (760, 0.5),
    "draw_recal_380_full": (380, 1.0),
}


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--leagues", default=LEAGUES, help="pooled for the decision")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")
    p.add_argument("--predictions-out", type=Path, help="write per-match predictions (JSONL)")


def draw_factors(rows: list[Row], window: int, weight: float) -> np.ndarray:
    """k per row from the same league's earlier predicted matches (results known
    by the row's fit time)."""
    k = np.ones(len(rows))
    by_league: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_league.setdefault(r.league, []).append(i)
    for idx in by_league.values():
        idx.sort(key=lambda i: rows[i].match.result.kickoff_at)
        known_at = [rows[i].match.result.kickoff_at + RESULT_DELAY for i in idx]
        draws = np.cumsum([0] + [int(rows[i].match.outcome_index == 1) for i in idx])
        pred = np.cumsum([0.0] + [rows[i].production[1] for i in idx])
        for i in idx:
            n_known = bisect.bisect_left(known_at, rows[i].fitted_at)  # known strictly before
            if n_known < window:
                continue
            lo = n_known - window
            observed, expected = draws[n_known] - draws[lo], pred[n_known] - pred[lo]
            ratio = observed / expected if expected > 0 else 1.0
            k[i] = min(max(1 + weight * (ratio - 1), K_MIN), K_MAX)
    return k


def apply_draw_factor(probs: np.ndarray, k: np.ndarray) -> np.ndarray:
    out = probs.copy()
    out[:, 1] *= k
    return out / out.sum(axis=1, keepdims=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
    params = ModelParams()
    rows: list[Row] = []
    for code in codes:
        matches = openfootball.load(FIRST, LAST, args.cache_dir, code)
        min_history = len([m for m in matches if m.result.season == FIRST])
        rows += production_rows(
            code, matches, params, min_history, [WARMUP[0], VALIDATION[0], FOLLOW_UP[0]]
        )
    prod = np.asarray([r.production for r in rows], dtype=float)
    seasons = np.array([r.match.result.season for r in rows])
    evaluated = np.isin(seasons, [*VALIDATION, *FOLLOW_UP])
    candidates, factors = {}, {}
    for name, (window, weight) in VARIANTS.items():
        k = np.where(evaluated, draw_factors(rows, window, weight), 1.0)
        candidates[name] = apply_draw_factor(prod, k)
        factors[name] = {
            season: {
                "mean_k": float(k[seasons == season].mean()),
                "min_k": float(k[seasons == season].min()),
                "max_k": float(k[seasons == season].max()),
            }
            for season in [*VALIDATION, *FOLLOW_UP]
        }
    ex = Experiment(rows, prod, candidates, factors)
    if args.predictions_out:
        write_predictions(args.predictions_out, [ex])
    validation, follow_up = ex.segment(VALIDATION), ex.segment(FOLLOW_UP)
    y = ex.outcomes
    draw_share = {
        s: {
            "observed": float((y[seasons == s] == 1).mean()),
            "predicted": float(prod[seasons == s, 1].mean()),
        }
        for s in [*VALIDATION, *FOLLOW_UP]
    }
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "draw_recalibration_v1",
        "production_model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "protocol": __doc__,
        "leagues": codes,
        "variants": {k: {"window": w, "weight": wt} for k, (w, wt) in VARIANTS.items()},
        "n_predicted": len(rows),
        "draw_share_by_season": draw_share,
        "factors": factors,
        "validation": validation,
        "follow_up": follow_up,
        "per_league_follow_up": {c: ex.segment(FOLLOW_UP, league=c) for c in codes},
        "gate": gate(validation, follow_up, list(VARIANTS)),
    }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
