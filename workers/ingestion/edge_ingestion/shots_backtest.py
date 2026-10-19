"""`edge backtest-shots` - does shot-based form improve the production model?

Pre-registered protocol (committed before the first run; do not edit after
results - add a dated addendum instead):

Question  Shots on target are less noisy than goals. Do features from a team's
          recent shots on target (and its finishing above or below them)
          improve the goal-based production model? (TODO #43)
Data      Club Football Match Data (football-data.co.uk results, shots, shots
          on target, Bet365 1X2 odds; MIT copy, file SHA-256 in the report),
          9 leagues pooled: en.1 en.2 de.1 de.2 es.1 it.1 fr.1 nl.1 pt.1,
          2018-19..2025-26 (same file and leagues as the market experiment).
Features  edge_ml.shots: for a forecast fitted at time T, only league matches
          with kickoff + 3 h < T count (the production results delay); last 10
          matches per team, fewer than 5 -> neutral; league references from
          the last 300 league matches. Variants: sot, finishing,
          sot_and_finishing.
Model     log lam_own' = log lam_own + a . x_own - b . x_opp on the production
          walk-forward expected goals (weekly refit, results enter training
          3 h after kickoff); a, b refitted before each season on every
          earlier season of all 9 leagues (Poisson MLE, production as offset).
Windows   2019-20 warm-up (first coefficients), 2020-21..2022-23 validation
          (choose one variant: lowest pooled log loss), 2023-24..2025-26
          follow-up.
Gate      validation gain >= 0.001 AND follow-up gain >= 0.002 AND weekly
          paired 95% CI upper bound < 0 AND Brier not worse (pooled), against
          production. Passing is a research result only: no automatic
          deployment (a model change needs Codex QA and the user's approval).
Descriptive (not part of the gate)
          - every variant against the de-margined Bet365 market on follow-up
            matches with odds (the bar the user wants to beat);
          - per-league follow-up log loss of the chosen variant;
          - coefficients per season; share of rows with neutral features.
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
    Row,
    compare,
    gate,
    metrics,
    production_rows,
    run_variants,
    write_predictions,
)
from edge_ingestion.history import club_match_data
from edge_ml.market import devig
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams
from edge_ml.shots import VARIANTS, ShotHistory

logger = logging.getLogger(__name__)

FIRST, LAST = "2018-19", "2025-26"
WARMUP = ["2019-20"]
VALIDATION = ["2020-21", "2021-22", "2022-23"]
FOLLOW_UP = ["2023-24", "2024-25", "2025-26"]
LEAGUES = "en.1,en.2,de.1,de.2,es.1,it.1,fr.1,nl.1,pt.1"


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--leagues", default=LEAGUES, help="pooled for the decision")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")
    p.add_argument("--predictions-out", type=Path, help="write per-match predictions (JSONL)")


def histories(
    codes: list[str], matches: dict[str, list[Any]], cache_dir: Path
) -> dict[str, ShotHistory]:
    out = {}
    for code in codes:
        shots = club_match_data.load_shots(code, cache_dir)
        h = ShotHistory()
        for m in matches[code]:
            s = shots.get(club_match_data.match_key(m.result))
            if s is None:
                continue
            r = m.result
            h.add(
                r.kickoff_at,
                r.home,
                r.away,
                r.home_goals,
                r.away_goals,
                s.home_on_target,
                s.away_on_target,
            )
        out[code] = h.freeze()
    return out


def _features(hist: dict[str, ShotHistory], variant: str):
    def build(rows: list[Row]) -> tuple[np.ndarray, np.ndarray]:
        x_h = [hist[r.league].features(r.match.result.home, r.fitted_at, variant) for r in rows]
        x_a = [hist[r.league].features(r.match.result.away, r.fitted_at, variant) for r in rows]
        return np.asarray(x_h, dtype=float), np.asarray(x_a, dtype=float)

    return build


def run(args: argparse.Namespace) -> dict[str, Any]:
    codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
    params = ModelParams()
    rows: list[Row] = []
    matches: dict[str, list[Any]] = {}
    counts: dict[str, dict[str, int]] = {}
    for code in codes:
        matches[code], counts[code] = club_match_data.load(code, FIRST, LAST, args.cache_dir)
        logger.info("shots backtest %s: %d matches", code, len(matches[code]))
        rows += production_rows(
            code,
            matches[code],
            params,
            counts[code].get(FIRST, 0),
            [WARMUP[0], VALIDATION[0], FOLLOW_UP[0]],
        )
    hist = histories(codes, matches, args.cache_dir)
    variants = {v: _features(hist, v) for v in VARIANTS}
    ex = run_variants(rows, variants, VALIDATION + FOLLOW_UP, params)
    if args.predictions_out:
        write_predictions(args.predictions_out, [ex])
    validation, follow_up = ex.segment(VALIDATION), ex.segment(FOLLOW_UP)
    decision = gate(validation, follow_up, list(VARIANTS))

    # descriptive: against the market on follow-up matches with odds
    y = ex.outcomes
    fu = np.isin(ex.seasons, FOLLOW_UP)
    with_odds = fu & np.array([r.match.odds is not None for r in rows])
    sub = [r for r, k in zip(rows, with_odds, strict=True) if k]
    market = np.asarray([devig(r.match.odds) for r in sub], dtype=float).reshape(-1, 3)
    vs_market = {
        "n_matches": int(with_odds.sum()),
        "market": metrics(market, y[with_odds]),
        "production": {
            **metrics(ex.production[with_odds], y[with_odds]),
            # market minus candidate: negative = the market is better
            "market_vs_this": compare(market, ex.production[with_odds], y[with_odds], sub),
        },
        **{
            name: {
                **metrics(p[with_odds], y[with_odds]),
                "market_vs_this": compare(market, p[with_odds], y[with_odds], sub),
            }
            for name, p in ex.candidates.items()
        },
    }
    neutral = {v: float(np.mean([not np.any(x) for x in variants[v](rows)[0]])) for v in VARIANTS}
    chosen = decision["selected_on_validation"]
    path = club_match_data.fetch(args.cache_dir)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "shot_form_v1",
        "production_model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "protocol": __doc__,
        "source": {
            "url": club_match_data.URL,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "attribution": "football-data.co.uk via xgabora/Club-Football-Match-Data (MIT)",
        },
        "leagues": codes,
        "matches_per_season": counts,
        "n_predicted": len(rows),
        "validation": validation,
        "follow_up": follow_up,
        "gate": decision,
        "coefficients": ex.coefficients,
        "descriptive": {
            "vs_market_follow_up": vs_market,
            "per_league_follow_up": {c: ex.segment(FOLLOW_UP, c).get(chosen) for c in codes},
            "neutral_feature_share_home": neutral,
        },
    }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report
