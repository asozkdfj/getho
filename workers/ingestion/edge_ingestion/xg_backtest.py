"""`edge backtest-xg` - does xG form improve on the shot-based form candidate?

Pre-registered protocol (committed 2026-10-20 before any xG data was seen; do
not edit after results - add a dated addendum instead):

Question  The shot-based candidate (`sot_and_finishing`, ADR-034) passed the
          standard gate against production. Does API-Football's post-match
          xG add to it or replace it with something better? (TODO #43 follow-up)
Data      Results, shots on target and Bet365 odds: Club Football Match Data
          (football-data.co.uk, MIT copy; same file as the shots experiment).
          xG: API-Football, exported with `edge export-match-stats` (ADR-038)
          for 2023, 2024 and 2025 seasons; CSV SHA-256 in the report.
Leagues   en.1 en.2 de.1 es.1 it.1 fr.1 nl.1 pt.1 (API 39 40 78 140 135 61 88 94).
          de.2 is excluded in advance: `check-xg` found no xG for it (nor for
          Austria) in 2023-24 and 2024-25.
Join      Per league, football-data match <- xG row with the same UK date and
          final score and the best team-name similarity; at least one name
          must match (difflib ratio >= 0.5, the `compare-shots` rule); each xG
          row is used once. Matches without a joined xG row add nothing to the
          xG history (features use joined matches only); coverage per league
          season is reported. Missing xG is never filled in.
Features  edge_ml.shots on the same terms as the shots experiment (last 10
          league matches with data whose kickoff + 3 h is before the fit time,
          fewer than 5 -> neutral, league references from the last 300 matches),
          fed with shots on target (SOT) or with xG:
            sot_and_finishing      SOT form + finishing vs SOT (reference)
            xg_and_finishing       xG form + finishing vs xG (replaces SOT)
            sot_finishing_plus_xg  the reference plus xG form (6 values)
Model     As the shots experiment: log lam' = log lam + a . x_own - b . x_opp on
          the production walk-forward expected goals (weekly refit, results 3 h
          after kickoff), a and b refitted before each season on every earlier
          season of all 8 leagues (Poisson MLE, production as offset).
Windows   2023-24 warm-up (first coefficients), 2024-25 validation (choose one
          of the two xG variants: lowest pooled log loss), 2025-26 follow-up.
          Every variant, the reference included, is fitted on the same seasons.
Gate      Against the REFERENCE `sot_and_finishing` (not production): validation
          gain >= 0.001 AND follow-up gain >= 0.002 AND weekly paired 95% CI
          upper bound < 0 AND Brier not worse (pooled). Passing is a research
          result only (no deployment without Codex QA and the user's approval).
Power     About 2,900 follow-up matches (8 leagues x 1 season): the weekly CI
          half-width is expected near 0.003 (0.0016 at 9,663 matches in the
          shots experiment). A gain below that is likely "inconclusive", which
          does not mean xG is useless.
Point in time
          The CSV has no observation times; like the shots experiment, xG
          counts from kickoff + 3 h. Live use would need the stored
          `match_statistics` times (ADR-029), checked separately.
Descriptive (not part of the gate)
          - every variant against production and against the de-margined Bet365
            market on follow-up matches with odds;
          - per-league follow-up log loss of the chosen variant vs the reference;
          - join coverage, coefficients per season, share of neutral features.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from edge_ingestion.feature_experiment import (
    MIN_FOLLOW_UP_GAIN,
    MIN_VALIDATION_GAIN,
    Row,
    compare,
    metrics,
    production_rows,
    run_variants,
    write_predictions,
)
from edge_ingestion.history import club_match_data
from edge_ingestion.history.football_data import UK
from edge_ingestion.shot_sources import MIN_NAME_SIMILARITY, _similarity
from edge_ingestion.shots_backtest import histories as sot_histories
from edge_ml.market import devig
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams
from edge_ml.shots import ShotHistory

logger = logging.getLogger(__name__)

FIRST, LAST = "2018-19", "2025-26"
WARMUP, VALIDATION, FOLLOW_UP = ["2023-24"], ["2024-25"], ["2025-26"]
API_LEAGUE = {
    "en.1": "39",
    "en.2": "40",
    "de.1": "78",
    "es.1": "140",
    "it.1": "135",
    "fr.1": "61",
    "nl.1": "88",
    "pt.1": "94",
}
REFERENCE = "sot_and_finishing"
XG_VARIANTS = ("xg_and_finishing", "sot_finishing_plus_xg")


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--xg-csv", type=Path, required=True, help="edge export-match-stats output")
    p.add_argument("--leagues", default=",".join(API_LEAGUE), help="pooled for the decision")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")
    p.add_argument("--predictions-out", type=Path, help="write per-match predictions (JSONL)")


def read_xg(text: str) -> dict[str, list[dict[str, Any]]]:
    """xG rows with both teams' xG, by API league id."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in csv.DictReader(io.StringIO(text)):
        if not (r.get("home_xg") and r.get("away_xg")):
            continue
        kickoff = datetime.fromisoformat(r["kickoff_at"])
        out[r["league_id"]].append(
            {
                "day": kickoff.astimezone(UK).date(),
                "score": (int(r["home_goals"]), int(r["away_goals"])),
                "home": r["home"],
                "away": r["away"],
                "xg": (float(r["home_xg"]), float(r["away_xg"])),
            }
        )
    return out


def join(matches: list[Any], rows: list[dict[str, Any]]) -> tuple[dict[Any, tuple], dict]:
    """football-data match key -> (home xG, away xG); and counts per season."""
    by_key: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_key[(r["day"], r["score"])].append(i)
    used: set[int] = set()
    out: dict[Any, tuple] = {}
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"matches": 0, "joined": 0})
    for m in matches:
        res = m.result
        counts[res.season]["matches"] += 1
        key = (res.kickoff_at.astimezone(UK).date(), (res.home_goals, res.away_goals))
        cands = [i for i in by_key.get(key, []) if i not in used]
        if not cands:
            continue

        scored = []
        for i in cands:
            sh = _similarity(res.home, rows[i]["home"])
            sa = _similarity(res.away, rows[i]["away"])
            scored.append((sh + sa, max(sh, sa), -i))
        _, either, neg = max(scored)
        if either < MIN_NAME_SIMILARITY:
            continue
        best = -neg
        used.add(best)
        out[club_match_data.match_key(res)] = rows[best]["xg"]
        counts[res.season]["joined"] += 1
    return out, dict(counts)


def xg_histories(
    codes: list[str], matches: dict[str, list[Any]], xg: dict[str, dict[Any, tuple]]
) -> dict[str, ShotHistory]:
    out = {}
    for code in codes:
        h = ShotHistory()
        for m in matches[code]:
            v = xg[code].get(club_match_data.match_key(m.result))
            if v is None:
                continue
            r = m.result
            h.add(r.kickoff_at, r.home, r.away, r.home_goals, r.away_goals, v[0], v[1])
        out[code] = h.freeze()
    return out


def _features(sot: dict[str, ShotHistory], xg: dict[str, ShotHistory], variant: str):
    def one(hist: dict[str, ShotHistory], kind: str, rows: list[Row], side: str) -> np.ndarray:
        return np.asarray(
            [
                hist[r.league].features(getattr(r.match.result, side), r.fitted_at, kind)
                for r in rows
            ],
            dtype=float,
        )

    def build(rows: list[Row]) -> tuple[np.ndarray, np.ndarray]:
        if variant == REFERENCE:
            return one(sot, REFERENCE, rows, "home"), one(sot, REFERENCE, rows, "away")
        if variant == "xg_and_finishing":
            return one(xg, "sot_and_finishing", rows, "home"), one(
                xg, "sot_and_finishing", rows, "away"
            )
        if variant == "sot_finishing_plus_xg":
            return (
                np.hstack([one(sot, REFERENCE, rows, "home"), one(xg, "sot", rows, "home")]),
                np.hstack([one(sot, REFERENCE, rows, "away"), one(xg, "sot", rows, "away")]),
            )
        raise ValueError(variant)

    return build


def gate_vs_reference(ex: Any, validation: dict[str, Any]) -> dict[str, Any]:
    """The pre-registered gate: the xG variant chosen on validation against the
    reference on the follow-up season."""
    chosen = min(XG_VARIANTS, key=lambda v: validation[v]["log_loss"])
    v_gain = validation[REFERENCE]["log_loss"] - validation[chosen]["log_loss"]
    fu = np.isin(ex.seasons, FOLLOW_UP)
    sub = [r for r, k in zip(ex.rows, fu, strict=True) if k]
    y = ex.outcomes[fu]
    vs = compare(ex.candidates[chosen][fu], ex.candidates[REFERENCE][fu], y, sub)
    checks = {
        "validation_gain>=0.001": v_gain >= MIN_VALIDATION_GAIN,
        "follow_up_gain>=0.002": -vs["log_loss_diff"] >= MIN_FOLLOW_UP_GAIN,
        "weekly_ci_upper<0": vs["log_loss_diff_ci95_weekly"][1] < 0,
        "brier_not_worse": vs["brier_diff"] <= 0,
    }
    lo, hi = vs["log_loss_diff_ci95_weekly"]
    if all(checks.values()):
        reading = "passes"
    elif lo > 0:
        reading = "worse than the reference"
    elif hi < 0:
        reading = "better than the reference but below the pre-registered size"
    else:
        reading = "inconclusive (CI includes 0)"
    return {
        "reference": REFERENCE,
        "selected_on_validation": chosen,
        "validation_gain_vs_reference": v_gain,
        "follow_up_vs_reference": vs,
        "follow_up_gain_vs_reference": -vs["log_loss_diff"],
        "checks": checks,
        "passes": all(checks.values()),
        "reading": reading,
        "deployed": False,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
    text = args.xg_csv.read_text(encoding="utf-8")
    xg_rows = read_xg(text)
    params = ModelParams()
    rows: list[Row] = []
    matches: dict[str, list[Any]] = {}
    counts: dict[str, dict[str, int]] = {}
    joined: dict[str, dict[Any, tuple]] = {}
    coverage: dict[str, dict[str, Any]] = {}
    for code in codes:
        matches[code], counts[code] = club_match_data.load(code, FIRST, LAST, args.cache_dir)
        joined[code], cov = join(matches[code], xg_rows.get(API_LEAGUE[code], []))
        coverage[code] = {s: c for s, c in cov.items() if s in WARMUP + VALIDATION + FOLLOW_UP}
        logger.info("xg backtest %s: %d matches, coverage %s", code, len(matches[code]), cov)
        rows += production_rows(
            code,
            matches[code],
            params,
            counts[code].get(FIRST, 0),
            [WARMUP[0], VALIDATION[0], FOLLOW_UP[0]],
        )
    sot = sot_histories(codes, matches, args.cache_dir)
    xg = xg_histories(codes, matches, joined)
    names = (REFERENCE, *XG_VARIANTS)
    variants = {v: _features(sot, xg, v) for v in names}
    ex = run_variants(rows, variants, VALIDATION + FOLLOW_UP, params)
    if args.predictions_out:
        write_predictions(args.predictions_out, [ex])
    validation, follow_up = ex.segment(VALIDATION), ex.segment(FOLLOW_UP)
    decision = gate_vs_reference(ex, validation)

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
    chosen = decision["selected_on_validation"]
    per_league = {}
    for code in codes:
        mask = fu & np.array([r.league == code for r in rows])
        lsub = [r for r, k in zip(rows, mask, strict=True) if k]
        if not lsub:
            continue
        per_league[code] = {
            "n_matches": int(mask.sum()),
            REFERENCE: metrics(ex.candidates[REFERENCE][mask], y[mask]),
            chosen: metrics(ex.candidates[chosen][mask], y[mask]),
            "vs_reference": compare(
                ex.candidates[chosen][mask], ex.candidates[REFERENCE][mask], y[mask], lsub
            ),
        }
    neutral = {v: float(np.mean([not np.any(x) for x in variants[v](rows)[0]])) for v in names}
    path = club_match_data.fetch(args.cache_dir)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "xg_form_v1",
        "production_model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "protocol": __doc__,
        "source": {
            "results_shots_odds": {
                "url": club_match_data.URL,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
            "xg_csv": {
                "name": args.xg_csv.name,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "rows_with_xg": {k: len(v) for k, v in sorted(xg_rows.items())},
            },
        },
        "leagues": codes,
        "join_coverage": coverage,
        "n_predicted": len(rows),
        "validation": validation,
        "follow_up": follow_up,
        "gate": decision,
        "coefficients": ex.coefficients,
        "descriptive": {
            "vs_market_follow_up": vs_market,
            "per_league_follow_up_vs_reference": per_league,
            "neutral_feature_share_home": neutral,
        },
    }
    if args.out:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report


def summary(report: dict[str, Any]) -> dict[str, Any]:
    g = report["gate"]
    return {
        "join_coverage": report["join_coverage"],
        "selected": g["selected_on_validation"],
        "validation_gain_vs_reference": round(g["validation_gain_vs_reference"], 6),
        "follow_up_gain_vs_reference": round(g["follow_up_gain_vs_reference"], 6),
        "ci95": g["follow_up_vs_reference"]["log_loss_diff_ci95_weekly"],
        "checks": g["checks"],
        "reading": g["reading"],
    }
