"""`edge backtest` - walk-forward evaluation on historical data.

    python -m edge_ingestion.cli backtest                       # openfootball, default split
    python -m edge_ingestion.cli backtest --tune --out report.json
    python -m edge_ingestion.cli backtest --source football-data --data-dir ./fd   # with odds

Split: seasons before --validation-from are warm-up (history only), seasons in
[--validation-from, --test-from) are used for tuning/calibration, seasons from
--test-from are scored once to decide promotion.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from edge_ml.backtest import BacktestConfig, evaluate, walk_forward
from edge_ml.experiments import (
    CalibratedForecaster,
    Split,
    coordinate_search,
    fit_temperature,
    params_to_dict,
    standard_forecasters,
)
from edge_ml.forecasters import BacktestMatch, ModelForecaster
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams
from edge_ml.picks import backtest_daily_picks
from edge_ml.promotion import decide

PICK_THRESHOLDS = [0.0, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75]

logger = logging.getLogger(__name__)


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--source", choices=["openfootball", "football-data"], default="openfootball")
    p.add_argument("--first-season", default="2018-19")
    p.add_argument("--last-season", default="2025-26")
    p.add_argument("--validation-from", default="2020-21")
    p.add_argument("--test-from", default="2023-24")
    p.add_argument("--data-dir", type=Path, help="football-data CSV directory (<season>.csv)")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--tune", action="store_true", help="coordinate search on validation seasons")
    p.add_argument("--out", type=Path, help="write the full JSON report here")


def _load(args: argparse.Namespace) -> tuple[list[BacktestMatch], dict[str, Any]]:
    if args.source == "openfootball":
        from edge_ingestion.history import openfootball

        matches = openfootball.load(args.first_season, args.last_season, args.cache_dir)
        source = {
            "name": "openfootball/football.json",
            "license": "public domain (CC0)",
            "odds": False,
        }
    else:
        from edge_ingestion.history import football_data

        if not args.data_dir:
            raise SystemExit("--data-dir is required for --source football-data")
        matches = football_data.load_dir(args.data_dir)
        source = {"name": "football-data.co.uk CSV", "license": "see provider terms", "odds": True}
    return matches, source


def _season_start(matches: list[BacktestMatch], season: str) -> datetime:
    starts = [m.result.kickoff_at for m in matches if m.result.season == season]
    if not starts:
        raise SystemExit(f"season {season} not in the dataset")
    return min(starts)


def run(args: argparse.Namespace) -> dict[str, Any]:
    matches, source = _load(args)
    has_odds = any(m.odds is not None for m in matches)
    split = Split(
        validation_start=_season_start(matches, args.validation_from),
        test_start=_season_start(matches, args.test_from),
    )
    production = ModelParams()
    report: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "data": {
            **source,
            "n_matches": len(matches),
            "seasons": sorted({m.result.season or "?" for m in matches}),
            "matches_with_odds": sum(1 for m in matches if m.odds is not None),
        },
        "split": {
            "warmup": f"< {args.validation_from}",
            "validation": f"{args.validation_from} .. < {args.test_from}",
            "test": f">= {args.test_from}",
        },
        "production": {
            "version": MODEL_VERSION,
            "feature_set": FEATURE_SET,
            "params": params_to_dict(production),
        },
    }

    candidate = None
    if args.tune:
        tuned = coordinate_search(matches, split, production, progress=logger.info)
        candidate = tuned.params
        report["tuning"] = {
            "baseline_validation_log_loss": tuned.baseline_log_loss,
            "tuned_validation_log_loss": tuned.tuned_log_loss,
            "steps": tuned.steps,
            "candidate_params": params_to_dict(candidate),
        }

    # Validation period: comparison + temperature fitted for the model we would ship.
    val_cfg = BacktestConfig(
        eval_start=split.validation_start, eval_end=split.test_start, reference="production"
    )
    val_preds = walk_forward(
        matches, standard_forecasters(production, candidate, has_odds), val_cfg
    )
    report["validation"] = evaluate(val_preds, val_cfg)
    ship_name = "candidate" if candidate is not None else "production"
    temperature = fit_temperature(val_preds, ship_name)
    report["calibration"] = {"model": ship_name, "temperature": temperature.temperature}

    # Test period: scored once with everything frozen.
    test_cfg = BacktestConfig(eval_start=split.test_start, reference="production")
    ship_params = candidate if candidate is not None else production
    forecasters = [
        *standard_forecasters(production, candidate, has_odds),
        CalibratedForecaster(
            ModelForecaster("_inner", dataclasses.replace(ship_params)),
            temperature,
            f"{ship_name}_calibrated",
        ),
    ]
    test_preds = walk_forward(matches, forecasters, test_cfg)
    report["test"] = evaluate(test_preds, test_cfg)
    # Today's Pick rule replayed on the frozen test predictions (production model).
    keys = [
        f"{m.result.kickoff_at.isoformat()}|{m.result.home}|{m.result.away}"
        for m in test_preds.matches
    ]
    report["daily_pick_backtest"] = {
        "model": "production",
        "tz": "Asia/Seoul",
        "rows": backtest_daily_picks(
            keys,
            [m.result.kickoff_at for m in test_preds.matches],
            test_preds.probs["production"],
            test_preds.outcomes,
            PICK_THRESHOLDS,
        ),
    }
    if candidate is not None:
        report["promotion"] = dataclasses.asdict(decide(report["test"]))
    report["promotion_calibrated"] = dataclasses.asdict(
        decide(report["test"], candidate=f"{ship_name}_calibrated")
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return report


def summary_table(report: dict[str, Any], period: str) -> str:
    sec = report[period]
    lines = [
        f"{period}: {sec['n_matches']} matches  observed H/D/A "
        + "/".join(f"{v:.3f}" for v in sec["observed_frequency"].values()),
        f"{'model':24s} {'log loss [95% CI]':28s} "
        f"{'Brier':>7s} {'RPS':>7s} {'acc':>6s} {'ECE':>6s}",
    ]
    for name, m in sec["models"].items():
        ll = m["log_loss"]
        lines.append(
            f"{name:24s} {ll['mean']:.4f} [{ll['ci_low']:.4f}, {ll['ci_high']:.4f}]  "
            f"{m['brier']['mean']:7.4f} {m['rps']['mean']:7.4f} "
            f"{m['accuracy']:6.3f} {m['ece']:6.3f}"
        )
    return "\n".join(lines)
