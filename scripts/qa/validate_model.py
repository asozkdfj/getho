"""Offline EPL replay and validation-selected probability-mixture experiment.

Run from repository root after caching openfootball 2018-19..2025-26.
Never downloads data or changes the production model.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "workers/ingestion")]

from edge_ingestion.history.openfootball import parse_season, season_labels, validate_season  # noqa: E402
from edge_ml.backtest import BacktestConfig, evaluate, walk_forward  # noqa: E402
from edge_ml.forecasters import BaseRateForecaster, EloOnlyForecaster, ModelForecaster  # noqa: E402
from edge_ml.metrics import brier_per_match, log_loss_per_match  # noqa: E402
from edge_ml.model import ModelParams  # noqa: E402
from edge_ml.picks import backtest_daily_picks  # noqa: E402


def weekly_ci(differences, matches):
    """Paired cluster bootstrap: sample ISO weeks, retain all matches in each.

    Uses a match-weighted mean for unequal cluster sizes. It is a sensitivity
    analysis; independence across weeks is still an assumption.
    """
    weeks = [m.result.kickoff_at.isocalendar()[:2] for m in matches]
    groups = sorted(set(weeks))
    sums = np.array(
        [sum(d for d, w in zip(differences, weeks, strict=True) if w == g) for g in groups]
    )
    sizes = np.array([weeks.count(g) for g in groups])
    rng = np.random.default_rng(20261016)
    idx = rng.integers(0, len(groups), size=(4000, len(groups)))
    means = sums[idx].sum(axis=1) / sizes[idx].sum(axis=1)
    return {
        "mean_diff": float(np.mean(differences)),
        "ci95": np.quantile(means, [0.025, 0.975]).tolist(),
        "weeks": len(groups),
    }


def main():
    out = ROOT / "docs/qa"
    inputs, matches, warnings = {}, [], []
    for season in season_labels("2018-19", "2025-26"):
        path = ROOT / f".cache/history/openfootball-en1-{season}.json"
        raw = path.read_bytes()
        inputs[path.name] = hashlib.sha256(raw).hexdigest()
        parsed = parse_season(json.loads(raw), season)
        warnings.extend(validate_season(parsed, season))
        matches.extend(parsed)
    if warnings:
        raise ValueError(f"EPL source integrity checks failed: {warnings}")

    def start(season):
        return min(m.result.kickoff_at for m in matches if m.result.season == season)

    params = ModelParams()

    def forecast():
        return [
            BaseRateForecaster(),
            EloOnlyForecaster(),
            ModelForecaster("production"),
            ModelForecaster("poisson_only", dataclasses.replace(params, poisson_weight=1.0)),
        ]

    cfg = BacktestConfig(
        eval_start=start("2020-21"),
        eval_end=start("2023-24"),
        reference="production",
        result_delay=timedelta(hours=3),
        bootstrap_resamples=2000,
    )
    timer = perf_counter()
    val = walk_forward(matches, forecast(), cfg)
    # Freeze a small, predeclared search on validation predictions only.
    search = []
    for weight in [0.0, 0.25, 0.5, 0.75, 1.0]:
        mixture = weight * val.probs["poisson_only"] + (1 - weight) * val.probs["elo_only"]
        search.append(
            {
                "poisson_weight": weight,
                "log_loss": float(log_loss_per_match(mixture, val.outcomes).mean()),
            }
        )
    best = min(search, key=lambda r: r["log_loss"])
    weight = best["poisson_weight"]
    baseline_val = float(log_loss_per_match(val.probs["production"], val.outcomes).mean())
    validation_pass = baseline_val - best["log_loss"] >= 0.001
    print(f"Validation complete: weight={weight}, passes={validation_pass}", flush=True)
    test_cfg = dataclasses.replace(cfg, eval_start=start("2023-24"), eval_end=None)
    test = walk_forward(matches, forecast(), test_cfg)
    test.probs["validation_selected_mixture"] = (
        weight * test.probs["poisson_only"] + (1 - weight) * test.probs["elo_only"]
    )
    report = evaluate(test, test_cfg)
    # Reproduce the old refit convention independently, without changing it.
    legacy = walk_forward(
        matches,
        [ModelForecaster("production")],
        dataclasses.replace(test_cfg, result_delay=timedelta(0)),
    )
    assert legacy.matches == test.matches
    y = test.outcomes
    production_loss = log_loss_per_match(test.probs["production"], y)
    comparisons = {}
    for name, p in test.probs.items():
        if name != "production":
            comparisons[name] = weekly_ci(log_loss_per_match(p, y) - production_loss, test.matches)
    comparisons["delay_3h_minus_legacy"] = weekly_ci(
        production_loss - log_loss_per_match(legacy.probs["production"], y), test.matches
    )
    keys = [
        f"{m.result.kickoff_at.isoformat()}|{m.result.home}|{m.result.away}" for m in test.matches
    ]
    kickoffs = [m.result.kickoff_at for m in test.matches]
    picks = {
        "whole_day": backtest_daily_picks(keys, kickoffs, test.probs["production"], y, [0.55]),
        "kst_09_timing_only": backtest_daily_picks(
            keys,
            kickoffs,
            test.probs["production"],
            y,
            [0.55],
            decision_hour=9,
            prediction_times=test.fitted_at,
        ),
    }
    outcome_slices = {}
    for season in sorted({m.result.season for m in test.matches}):
        rows = np.array([m.result.season == season for m in test.matches])
        outcome_slices[season] = {
            label: {
                "n": int((rows & (y == k)).sum()),
                "log_loss": float(production_loss[rows & (y == k)].mean()),
                "loss_contribution": float(production_loss[rows & (y == k)].sum() / rows.sum()),
            }
            for k, label in enumerate(["home", "draw", "away"])
        }
    candidate = "validation_selected_mixture"
    ci = comparisons[candidate]
    brier_gain = float(
        (
            brier_per_match(test.probs[candidate], y) - brier_per_match(test.probs["production"], y)
        ).mean()
    )
    research_pass = bool(
        validation_pass and ci["ci95"][1] < 0 and ci["mean_diff"] <= -0.002 and brier_gain <= 0
    )
    artifacts = out / "model-validation-predictions.jsonl"
    with artifacts.open("w", encoding="utf-8", newline="\n") as f:
        for i, m in enumerate(test.matches):
            r = m.result
            row = {
                "key": keys[i],
                "season": r.season,
                "kickoff_at": r.kickoff_at.isoformat(),
                "fitted_at": test.fitted_at[i].isoformat(),
                "outcome": int(y[i]),
                "probabilities": {n: p[i].tolist() for n, p in test.probs.items()},
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_hashes": inputs,
        "python": sys.version,
        "numpy": np.__version__,
        "matches_loaded": len(matches),
        "source_warnings": warnings,
        "runtime_seconds": perf_counter() - timer,
        "scope": "EPL retrospective research; previously inspected test period; not live replay",
        "protocol": {
            "validation": "2020-21..2022-23",
            "test": "2023-24..2025-26",
            "refit_days": 7,
            "result_delay_hours": 3,
            "delay_limit": "assumed result availability, not observed provider timestamps",
        },
        "search": search,
        "validation_production_log_loss": baseline_val,
        "selected_poisson_weight": weight,
        "validation_pass": validation_pass,
        "test": report,
        "weekly_paired_comparisons": comparisons,
        "legacy_production": evaluate(legacy, test_cfg),
        "daily_picks": picks,
        "outcome_slices": outcome_slices,
        "research_gate_pass": research_pass,
        "production_changed": False,
        "prediction_artifact_sha256": hashlib.sha256(artifacts.read_bytes()).hexdigest(),
    }
    target = out / "model-validation-results.json"
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(f"Saved {target}; research gate={research_pass}", flush=True)


if __name__ == "__main__":
    main()
