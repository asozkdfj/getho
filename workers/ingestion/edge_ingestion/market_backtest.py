"""`edge backtest-market` - model vs market, and does blending with the market help?

Pre-registered protocol (committed before the first run; do not edit after results):

Data     Club Football Match Data (football-data.co.uk results + Bet365 1X2
         pre-match odds, MIT copy on GitHub), 2018-19..2025-26; file SHA-256
         in the report. 9 leagues pooled: en.1 en.2 de.1 de.2 es.1 it.1 fr.1
         nl.1 pt.1 (at.1 is not in this file's verified set and has a split
         format). The production model is trained on these results.
Timing   Production model refitted weekly, results enter training 3 h after
         kickoff, refit grid restarts at the warm-up, validation and
         follow-up starts (same engine as the other experiments).
Market   Bet365 odds with the margin removed proportionally (as the service
         does). The capture time of these odds is not documented: they are
         pre-match but may be later than the service's 09:00 KST decision.
Part A   Measurement only, no decision: production vs market on validation
         (2020-21..2022-23) and follow-up (2023-24..2025-26): log loss, Brier,
         accuracy, weekly paired 95% CI.
Part B   Candidate: linear pool  p = w * production + (1 - w) * market,
         w in {0.25, 0.50, 0.75}; choose w on validation (lowest pooled log
         loss). Market alone (w = 0) is reported but is NOT a candidate: the
         service's analysis must stay an estimate of its own that can be
         compared with the market.
Gate     validation gain >= 0.001 AND follow-up gain >= 0.002 AND weekly
         paired 95% CI upper bound < 0 AND Brier not worse (pooled), against
         production. Passing is a research result only: no automatic
         deployment (a blend would also change what the "gap vs market"
         numbers in the product mean - a product decision).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from edge_ingestion.feature_experiment import (
    Experiment,
    Row,
    compare,
    gate,
    metrics,
    production_rows,
    write_predictions,
)
from edge_ingestion.history import club_match_data
from edge_ml.market import devig
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams

logger = logging.getLogger(__name__)

FIRST, LAST = "2018-19", "2025-26"
WARMUP = ["2019-20"]
VALIDATION = ["2020-21", "2021-22", "2022-23"]
FOLLOW_UP = ["2023-24", "2024-25", "2025-26"]
LEAGUES = "en.1,en.2,de.1,de.2,es.1,it.1,fr.1,nl.1,pt.1"
WEIGHTS = (0.25, 0.50, 0.75)


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--leagues", default=LEAGUES, help="pooled for the decision")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")
    p.add_argument("--predictions-out", type=Path, help="write per-match predictions (JSONL)")


def market_probs(rows: list[Row]) -> np.ndarray:
    return np.asarray([devig(r.match.odds) for r in rows], dtype=float).reshape(-1, 3)


def run(args: argparse.Namespace) -> dict[str, Any]:
    codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
    params = ModelParams()
    rows: list[Row] = []
    counts: dict[str, dict[str, int]] = {}
    for code in codes:
        matches, counts[code] = club_match_data.load(code, FIRST, LAST, args.cache_dir)
        min_history = counts[code].get(FIRST, 0)
        logger.info("market backtest %s: %d matches", code, len(matches))
        rows += production_rows(
            code, matches, params, min_history, [WARMUP[0], VALIDATION[0], FOLLOW_UP[0]]
        )
    n_all = len(rows)
    rows = [r for r in rows if r.match.odds is not None]  # common sample: odds known
    prod = np.asarray([r.production for r in rows], dtype=float)
    market = market_probs(rows)
    candidates = {f"blend_w{w:.2f}": w * prod + (1 - w) * market for w in WEIGHTS}
    candidates["market_only"] = market  # reference, never a candidate
    ex = Experiment(rows, prod, candidates, {})
    if args.predictions_out:
        write_predictions(args.predictions_out, [ex])

    validation, follow_up = ex.segment(VALIDATION), ex.segment(FOLLOW_UP)
    y = ex.outcomes
    seasons = ex.seasons

    def model_vs_market(names: list[str], league: str | None = None) -> dict[str, Any]:
        mask = np.isin(seasons, names)
        if league is not None:
            mask &= np.array([r.league == league for r in rows])
        sub = [r for r, k in zip(rows, mask, strict=True) if k]
        return {
            "n_matches": int(mask.sum()),
            "production": metrics(prod[mask], y[mask]),
            "market": metrics(market[mask], y[mask]),
            # market minus production: negative = the market is better
            "market_vs_production": compare(market[mask], prod[mask], y[mask], sub),
        }

    path = club_match_data.fetch(args.cache_dir)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "market_baseline_and_blend_v1",
        "production_model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "protocol": __doc__,
        "source": {
            "url": club_match_data.URL,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "attribution": "football-data.co.uk via xgabora/Club-Football-Match-Data (MIT)",
        },
        "leagues": codes,
        "matches_per_season": counts,
        "n_predicted": n_all,
        "n_with_odds": len(rows),
        "part_a_model_vs_market": {
            "validation": model_vs_market(VALIDATION),
            "follow_up": model_vs_market(FOLLOW_UP),
            "per_league_follow_up": {c: model_vs_market(FOLLOW_UP, c) for c in codes},
        },
        "validation": validation,
        "follow_up": follow_up,
        "gate": gate(validation, follow_up, [f"blend_w{w:.2f}" for w in WEIGHTS]),
    }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
