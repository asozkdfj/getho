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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from edge_ingestion.history import openfootball, openfootball_txt
from edge_ml.backtest import BacktestConfig, evaluate, walk_forward
from edge_ml.core import Probabilities1X2
from edge_ml.fatigue import VARIANTS, Appearance, Schedule, adjust, fit
from edge_ml.forecasters import BacktestMatch, ModelForecaster
from edge_ml.metrics import (
    accuracy_per_match,
    brier_per_match,
    cluster_bootstrap_ci,
    expected_calibration_error,
    log_loss_per_match,
)
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams, PoissonEloModel
from edge_ml.poisson import probabilities_from_expected_goals

logger = logging.getLogger(__name__)

FIRST, LAST = "2018-19", "2025-26"
WARMUP = ["2019-20"]
VALIDATION = ["2020-21", "2021-22", "2022-23"]
FOLLOW_UP = ["2023-24", "2024-25"]
SENSITIVITY = ["2025-26"]
RESULT_DELAY = timedelta(hours=3)
REFIT_EVERY = timedelta(days=7)
MIN_VALIDATION_GAIN, MIN_FOLLOW_UP_GAIN = 0.001, 0.002
DIAGNOSTIC = "rest_league_only"  # same "rest" feature from league matches only


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--leagues", default="en.1,en.2", help="first league decides, others replicate")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the JSON report here")
    p.add_argument("--predictions-out", type=Path, help="write per-match predictions (JSONL)")


@dataclass(slots=True)
class Row:
    match: BacktestMatch
    fitted_at: datetime
    lam_h: float
    lam_a: float
    production: tuple[float, float, float]


def _season_start(matches: Sequence[BacktestMatch], season: str) -> datetime:
    return min(m.result.kickoff_at for m in matches if m.result.season == season)


def production_rows(
    matches: Sequence[BacktestMatch], params: ModelParams, min_history: int
) -> list[Row]:
    """Walk-forward production expected goals. The weekly refit grid restarts at
    the warm-up, validation and follow-up starts, exactly like the QA replay."""
    ordered = sorted(matches, key=lambda m: (m.result.kickoff_at, m.result.home, m.result.away))
    results = [m.result for m in ordered]
    anchors = [_season_start(ordered, s) for s in (WARMUP[0], VALIDATION[0], FOLLOW_UP[0])]
    ends = [*anchors[1:], ordered[-1].result.kickoff_at + timedelta(seconds=1)]
    rows: list[Row] = []
    for start, end in zip(anchors, ends, strict=True):
        as_of = start
        while as_of < end:
            window_end = min(as_of + REFIT_EVERY, end)
            window = [m for m in ordered if as_of <= m.result.kickoff_at < window_end]
            history = [r for r in results if r.kickoff_at + RESULT_DELAY < as_of]
            if window and len(history) >= min_history:
                model = PoissonEloModel(params=params).fit(history, as_of)
                for m in window:
                    out = model.predict(m.result.home, m.result.away)
                    rows.append(
                        Row(
                            m,
                            as_of,
                            out.expected_goals_home,
                            out.expected_goals_away,
                            out.probabilities.as_tuple(),
                        )
                    )
            as_of = window_end
    return rows


def _probs(lam_h: np.ndarray, lam_a: np.ndarray, params: ModelParams) -> np.ndarray:
    out = []
    for h, a in zip(lam_h, lam_a, strict=True):
        p = probabilities_from_expected_goals(
            max(float(h), params.min_lambda),
            max(float(a), params.min_lambda),
            params.max_goals,
            params.dixon_coles_rho,
        )
        if params.draw_inflation != 1.0:
            p = Probabilities1X2.normalized(p.home, p.draw * params.draw_inflation, p.away)
        out.append(p.as_tuple())
    return np.asarray(out, dtype=float).reshape(-1, 3)


def _features(rows: list[Row], schedule: Schedule, variant: str) -> tuple[np.ndarray, np.ndarray]:
    fn = VARIANTS["rest" if variant == DIAGNOSTIC else variant]
    x_h = [fn(schedule.features(r.match.result.home, r.match.result.kickoff_at)) for r in rows]
    x_a = [fn(schedule.features(r.match.result.away, r.match.result.kickoff_at)) for r in rows]
    return np.asarray(x_h, dtype=float), np.asarray(x_a, dtype=float)


def _metrics(probs: np.ndarray, y: np.ndarray) -> dict[str, float]:
    return {
        "log_loss": float(log_loss_per_match(probs, y).mean()),
        "brier": float(brier_per_match(probs, y).mean()),
        "accuracy": float(accuracy_per_match(probs, y).mean()),
        "ece": float(expected_calibration_error(probs, y)),
    }


def _compare(cand: np.ndarray, prod: np.ndarray, y: np.ndarray, rows: list[Row]) -> dict[str, Any]:
    diff = log_loss_per_match(cand, y) - log_loss_per_match(prod, y)
    weeks = [r.match.result.kickoff_at.isocalendar()[:2] for r in rows]
    lo, hi = cluster_bootstrap_ci(diff, weeks)
    return {
        "log_loss_diff": float(diff.mean()),
        "log_loss_diff_ci95_weekly": [lo, hi],
        "brier_diff": float((brier_per_match(cand, y) - brier_per_match(prod, y)).mean()),
        "accuracy_diff": float((accuracy_per_match(cand, y) - accuracy_per_match(prod, y)).mean()),
        "weeks": len(set(weeks)),
    }


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
) -> dict[str, Any]:
    params = ModelParams()
    min_history = len([m for m in matches if m.result.season == FIRST])
    rows = production_rows(matches, params, min_history)
    seasons = np.array([r.match.result.season for r in rows])
    y = np.array([r.match.outcome_index for r in rows], dtype=int)
    lam_h = np.array([r.lam_h for r in rows])
    lam_a = np.array([r.lam_a for r in rows])
    goals_h = np.array([r.match.result.home_goals for r in rows], dtype=float)
    goals_a = np.array([r.match.result.away_goals for r in rows], dtype=float)
    prod = np.asarray([r.production for r in rows], dtype=float)
    # The adjusted model with zero coefficients must be the production model.
    assert np.allclose(_probs(lam_h, lam_a, params), prod, atol=1e-9)

    candidates: dict[str, np.ndarray] = {}
    fits: dict[str, dict[str, Any]] = {}
    for variant in [*VARIANTS, DIAGNOSTIC]:
        schedule = league_only if variant == DIAGNOSTIC else full
        x_h, x_a = _features(rows, schedule, variant)
        probs = prod.copy()
        fits[variant] = {}
        for season in [*VALIDATION, *FOLLOW_UP, *SENSITIVITY]:
            train = np.array([s < season for s in seasons])  # every earlier season
            target = seasons == season
            f = fit(
                lam_h[train], lam_a[train], x_h[train], x_a[train], goals_h[train], goals_a[train]
            )
            fits[variant][season] = {
                "own": f.own,
                "opponent": f.opponent,
                "n_matches": f.n_matches,
                "log_likelihood_gain": f.log_likelihood_gain,
            }
            adj_h, adj_a = adjust(
                lam_h[target], lam_a[target], x_h[target], x_a[target], f.own, f.opponent
            )
            probs[target] = _probs(adj_h, adj_a, params)
        candidates[variant] = probs

    def segment(names: list[str]) -> dict[str, Any]:
        mask = np.isin(seasons, names)
        sub = [r for r, k in zip(rows, mask, strict=True) if k]
        out: dict[str, Any] = {
            "seasons": names,
            "n_matches": int(mask.sum()),
            "production": _metrics(prod[mask], y[mask]),
        }
        for name, p in candidates.items():
            out[name] = {
                **_metrics(p[mask], y[mask]),
                "vs_production": _compare(p[mask], prod[mask], y[mask], sub),
            }
        return out

    return {
        "league": code,
        "n_predicted": len(rows),
        "min_history": min_history,
        "fatigue_profile": _fatigue_summary(
            [r for r in rows if r.match.result.season != "2025-26"], full
        ),
        "fatigue_profile_2025_26_incomplete": _fatigue_summary(
            [r for r in rows if r.match.result.season == "2025-26"], full
        ),
        "coefficients": fits,
        "validation": segment(VALIDATION),
        "follow_up": segment(FOLLOW_UP),
        "sensitivity_2025_26": segment(SENSITIVITY),
        "follow_up_incl_2025_26": segment([*FOLLOW_UP, *SENSITIVITY]),
        "_rows": rows,
        "_candidates": candidates,
        "_production": prod,
    }


def gate(primary: dict[str, Any]) -> dict[str, Any]:
    val = primary["validation"]
    variants = list(VARIANTS)  # the diagnostic is never a candidate
    chosen = min(variants, key=lambda v: val[v]["log_loss"])
    v_gain = val["production"]["log_loss"] - val[chosen]["log_loss"]
    fu = primary["follow_up"][chosen]["vs_production"]
    checks = {
        "validation_gain>=0.001": v_gain >= MIN_VALIDATION_GAIN,
        "follow_up_gain>=0.002": -fu["log_loss_diff"] >= MIN_FOLLOW_UP_GAIN,
        "weekly_ci_upper<0": fu["log_loss_diff_ci95_weekly"][1] < 0,
        "brier_not_worse": fu["brier_diff"] <= 0,
    }
    return {
        "selected_on_validation": chosen,
        "validation_gain": v_gain,
        "follow_up_gain": -fu["log_loss_diff"],
        "checks": checks,
        "passes": all(checks.values()),
        "deployed": False,
    }


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
    results = []
    for code in codes:
        league_only = Schedule(_appearances(leagues[code], []))
        logger.info("fatigue backtest %s: %d matches", code, len(leagues[code]))
        results.append(run_league(code, leagues[code], full, league_only))

    if args.predictions_out:
        with args.predictions_out.open("w", encoding="utf-8") as f:
            for res in results:
                for i, r in enumerate(res["_rows"]):
                    m = r.match.result
                    row = {
                        "league": res["league"],
                        "season": m.season,
                        "kickoff_at": m.kickoff_at.isoformat(),
                        "home": m.home,
                        "away": m.away,
                        "fitted_at": r.fitted_at.isoformat(),
                        "outcome": r.match.outcome_index,
                        "production": [round(v, 6) for v in res["_production"][i]],
                        **{k: [round(v, 6) for v in p[i]] for k, p in res["_candidates"].items()},
                    }
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
    for res in results:
        for key in ("_rows", "_candidates", "_production"):
            res.pop(key)

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
        "gate": gate(results[0]),
        "replication": {res["league"]: gate(res) for res in results[1:]},
        "qa_reproduction": reproduce_qa(leagues.get("en.1")) if "en.1" in leagues else None,
    }
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def reproduce_qa(matches: list[BacktestMatch]) -> dict[str, Any]:
    """The QA branch's EPL baseline (3 h delay, weekly grid from 2023-24)."""
    cfg = BacktestConfig(
        eval_start=_season_start(matches, FOLLOW_UP[0]),
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
