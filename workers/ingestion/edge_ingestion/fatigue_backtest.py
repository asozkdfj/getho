"""`edge backtest-fatigue` - do rest days / fixture congestion improve the model?

Pre-registered protocol (committed before the first run; do not edit after results):

Data     openfootball league files (football.json) + FA Cup, EFL Cup, Champions /
         Europa / Conference League (Football.TXT) -> every match a club played.
Leagues  Premier League (primary decision), Championship (replication only).
Timing   Production model refitted weekly, a match result enters training 3 h
         after kickoff (assumed availability lag, as in the QA protocol).
         Fatigue features use only matches on earlier calendar days.
Windows  2019-20             warm-up: production predictions used only to fit
                             the first fatigue coefficients
         2020-21..2022-23    validation: pick one variant (lowest log loss)
         2023-24..2024-25    follow-up, PRIMARY (complete cup/Europe coverage)
         2025-26             sensitivity only: domestic cups, Europa and
                             Conference League files are not published
         Coefficients are refitted before each season on all earlier seasons.
Gate     validation log loss gain >= 0.001 AND follow-up gain >= 0.002 AND
         weekly paired 95% CI upper bound < 0 AND Brier not worse.
         Passing the gate is a research result: no automatic deployment; a
         new period or shadow run must confirm it first.
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
    RESULT_DELAY,
    Experiment,
    Row,
    gate,
    production_rows,
    run_variants,
    season_start,
    write_predictions,
)
from edge_ingestion.history import openfootball, openfootball_txt
from edge_ml.backtest import BacktestConfig, evaluate, walk_forward
from edge_ml.fatigue import VARIANTS, Appearance, Schedule
from edge_ml.forecasters import BacktestMatch, ModelForecaster
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams

logger = logging.getLogger(__name__)

FIRST, LAST = "2018-19", "2025-26"
WARMUP = ["2019-20"]
VALIDATION = ["2020-21", "2021-22", "2022-23"]
FOLLOW_UP = ["2023-24", "2024-25"]
SENSITIVITY = ["2025-26"]
DIAGNOSTIC = "rest_league_only"  # same "rest" feature from league matches only


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--leagues", default="en.1,en.2", help="first league decides, others replicate")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")
    p.add_argument("--predictions-out", type=Path, help="write per-match predictions (JSONL)")


def _features(schedule: Schedule, variant: str):
    fn = VARIANTS["rest" if variant == DIAGNOSTIC else variant]

    def build(rows: list[Row]) -> tuple[np.ndarray, np.ndarray]:
        x_h = [fn(schedule.features(r.match.result.home, r.match.result.kickoff_at)) for r in rows]
        x_a = [fn(schedule.features(r.match.result.away, r.match.result.kickoff_at)) for r in rows]
        return np.asarray(x_h, dtype=float), np.asarray(x_a, dtype=float)

    return build


def _fatigue_summary(rows: list[Row], schedule: Schedule) -> dict[str, Any]:
    feats = [
        schedule.features(team, r.match.result.kickoff_at)
        for r in rows
        for team in (r.match.result.home, r.match.result.away)
    ]
    n = len(feats)
    return {
        "team_matches": n,
        "rest_le_3_days": sum(f.rest_days <= 3 for f in feats) / n,
        "rest_4_5_days": sum(4 <= f.rest_days <= 5 for f in feats) / n,
        "rest_ge_6_days": sum(f.rest_days >= 6 for f in feats) / n,
        "mean_load_14": float(np.mean([f.load_14 for f in feats])),
        "extra_time_4d": sum(f.extra_time_4d for f in feats) / n,
        "europe_4d": sum(f.europe_4d for f in feats) / n,
    }


def run_league(
    code: str, matches: list[BacktestMatch], full: Schedule, league_only: Schedule
) -> tuple[dict[str, Any], Experiment]:
    params = ModelParams()
    min_history = len([m for m in matches if m.result.season == FIRST])
    rows = production_rows(
        code, matches, params, min_history, [WARMUP[0], VALIDATION[0], FOLLOW_UP[0]]
    )
    variants = {v: _features(full, v) for v in VARIANTS}
    variants[DIAGNOSTIC] = _features(league_only, DIAGNOSTIC)
    ex = run_variants(rows, variants, [*VALIDATION, *FOLLOW_UP, *SENSITIVITY], params)
    result = {
        "league": code,
        "n_predicted": len(rows),
        "min_history": min_history,
        "fatigue_profile": _fatigue_summary(
            [r for r in rows if r.match.result.season != "2025-26"], full
        ),
        "fatigue_profile_2025_26_incomplete": _fatigue_summary(
            [r for r in rows if r.match.result.season == "2025-26"], full
        ),
        "coefficients": ex.coefficients,
        "validation": ex.segment(VALIDATION),
        "follow_up": ex.segment(FOLLOW_UP),
        "sensitivity_2025_26": ex.segment(SENSITIVITY),
        "follow_up_incl_2025_26": ex.segment([*FOLLOW_UP, *SENSITIVITY]),
    }
    return result, ex


def _gate(result: dict[str, Any]) -> dict[str, Any]:
    # the diagnostic is never a candidate
    return gate(result["validation"], result["follow_up"], list(VARIANTS))


def _appearances(
    matches: list[BacktestMatch], cups: list[openfootball_txt.CupMatch]
) -> list[Appearance]:
    out = [
        Appearance(team, m.result.kickoff_at, "league")
        for m in matches
        for team in (m.result.home, m.result.away)
    ]
    out += [
        Appearance(team, c.kickoff_at, c.competition, c.extra_time)
        for c in cups
        for team in (c.home, c.away)
    ]
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    codes = [c.strip() for c in args.leagues.split(",") if c.strip()]
    seasons = openfootball.season_labels(FIRST, LAST)
    leagues = {code: openfootball.load(FIRST, LAST, args.cache_dir, code) for code in codes}
    cups, missing = openfootball_txt.load(seasons, args.cache_dir)
    every_league = [m for ms in leagues.values() for m in ms]
    full = Schedule(_appearances(every_league, cups))
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(args.cache_dir.glob("openfootball-*"))
        if p.suffix in {".json", ".txt"} and any(s in p.name for s in seasons)
    }
    results, experiments = [], []
    for code in codes:
        league_only = Schedule(_appearances(leagues[code], []))
        logger.info("fatigue backtest %s: %d matches", code, len(leagues[code]))
        result, ex = run_league(code, leagues[code], full, league_only)
        results.append(result)
        experiments.append(ex)
    if args.predictions_out:
        write_predictions(args.predictions_out, experiments)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "fatigue_rest_v1",
        "production_model": {"version": MODEL_VERSION, "feature_set": FEATURE_SET},
        "protocol": __doc__,
        "variants": list(VARIANTS),
        "diagnostic": DIAGNOSTIC,
        "missing_source_files": missing,
        "source_sha256": hashes,
        "leagues": results,
        "gate": _gate(results[0]),
        "replication": {res["league"]: _gate(res) for res in results[1:]},
        "qa_reproduction": reproduce_qa(leagues.get("en.1")) if "en.1" in leagues else None,
    }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def reproduce_qa(matches: list[BacktestMatch]) -> dict[str, Any]:
    """The QA branch's EPL baseline (3 h delay, weekly grid from 2023-24)."""
    cfg = BacktestConfig(
        eval_start=season_start(matches, FOLLOW_UP[0]),
        reference="production",
        result_delay=RESULT_DELAY,
        bootstrap_resamples=200,
    )
    preds = walk_forward(matches, [ModelForecaster("production")], cfg)
    m = evaluate(preds, cfg)["models"]["production"]
    return {
        "n_matches": len(preds.matches),
        "log_loss": m["log_loss"]["mean"],
        "accuracy": m["accuracy"],
        "qa_reported": {"n_matches": 1140, "log_loss": 0.983187, "accuracy": 0.5219},
    }
