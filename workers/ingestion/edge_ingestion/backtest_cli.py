"""`edge backtest` - walk-forward evaluation on historical data.

    python -m edge_ingestion.cli backtest                       # openfootball, default split
    python -m edge_ingestion.cli backtest --tune --out report.json
    python -m edge_ingestion.cli backtest --source football-data --data-dir ./fd   # with odds
    python -m edge_ingestion.cli backtest --leagues en.1,de.1,es.1 --out report.json

With several --leagues the first one gets the detailed report (tuning,
calibration, promotion) and every league is scored on its test seasons with the
unchanged production model against the baselines. A league counts as
"verified" when the model is clearly better than the base-rate baseline there.
The Today's Pick rule is replayed on the pooled test predictions of the
verified leagues, as the service picks across them.

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

import numpy as np

from edge_ml.backtest import BacktestConfig, evaluate, walk_forward
from edge_ml.experiments import (
    CalibratedForecaster,
    Split,
    coordinate_search,
    fit_temperature,
    params_to_dict,
    standard_forecasters,
)
from edge_ml.forecasters import (
    BacktestMatch,
    BaseRateForecaster,
    EloOnlyForecaster,
    ModelForecaster,
)
from edge_ml.model import FEATURE_SET, MODEL_VERSION, ModelParams
from edge_ml.picks import backtest_daily_picks
from edge_ml.promotion import decide

PICK_DECISION_HOUR = 9  # matches the service default PICK_PUBLISH_HOUR
PICK_THRESHOLDS = [0.0, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8]
# A league is "verified" only with enough test matches and a clear win over base rate.
MIN_VERIFIED_TEST_MATCHES = 300

logger = logging.getLogger(__name__)


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--source", choices=["openfootball", "football-data"], default="openfootball")
    p.add_argument(
        "--leagues",
        default="en.1",
        help="openfootball league codes, comma-separated (first = detailed report)",
    )
    p.add_argument("--first-season", default="2018-19")
    p.add_argument("--last-season", default="2025-26")
    p.add_argument("--validation-from", default="2020-21")
    p.add_argument("--test-from", default="2023-24")
    p.add_argument("--data-dir", type=Path, help="football-data CSV directory (<season>.csv)")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--tune", action="store_true", help="coordinate search on validation seasons")
    p.add_argument("--out", type=Path, help="write the full JSON report here")
    p.add_argument(
        "--market-report",
        type=Path,
        help="attach the summary of an `edge backtest-market` report (model vs market)",
    )


def _codes(args: argparse.Namespace) -> list[str]:
    return [c.strip() for c in getattr(args, "leagues", "en.1").split(",") if c.strip()]


def _load(args: argparse.Namespace) -> tuple[list[BacktestMatch], dict[str, Any]]:
    if args.source == "openfootball":
        from edge_ingestion.history import openfootball

        matches = openfootball.load(
            args.first_season, args.last_season, args.cache_dir, _codes(args)[0]
        )
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
    _add_leagues(report, args, test_preds)
    if getattr(args, "market_report", None):
        report["market_baseline"] = market_baseline(json.loads(args.market_report.read_text()))
    if candidate is not None:
        report["promotion"] = dataclasses.asdict(decide(report["test"]))
    report["promotion_calibrated"] = dataclasses.asdict(
        decide(report["test"], candidate=f"{ship_name}_calibrated")
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return report


def _metrics(model: dict[str, Any]) -> dict[str, float]:
    return {
        "log_loss": model["log_loss"]["mean"],
        "brier": model["brier"]["mean"],
        "accuracy": model["accuracy"],
        "ece": model["ece"],
    }


def league_summary(code: str, evaluation: dict[str, Any], n_total: int) -> dict[str, Any]:
    """Per-league verdict from a test-period evaluation with reference=production."""
    from edge_ingestion.history.openfootball import LEAGUES

    models = evaluation["models"]
    vs = models["base_rate"]["vs_reference"]["log_loss"]  # base_rate - production
    meta = LEAGUES.get(code)
    n = evaluation["n_matches"]
    return {
        "code": code,
        "name": meta.name if meta else code,
        "country": meta.country if meta else "",
        "provider_ids": {"api_football": meta.api_football_id} if meta else {},
        "n_matches": n_total,
        "test_matches": n,
        "test_first_kickoff": evaluation["first_kickoff"],
        "models": {name: _metrics(m) for name, m in models.items()},
        # positive = production has the lower (better) log loss
        "gain_vs_base_rate": {
            "mean": vs["mean_diff"],
            "ci_low": vs["ci_low"],
            "ci_high": vs["ci_high"],
        },
        "verified": bool(n >= MIN_VERIFIED_TEST_MATCHES and vs["ci_low"] > 0),
    }


def market_baseline(market: dict[str, Any]) -> dict[str, Any]:
    """The parts of a market-baseline report the performance page shows."""
    part_a = market["part_a_model_vs_market"]
    fu = part_a["follow_up"]
    return {
        "source": market["source"],
        "leagues": market["leagues"],
        "period": ">= " + market["follow_up"]["seasons"][0],
        "n_matches": fu["n_matches"],
        "production": fu["production"],
        "market": fu["market"],
        "log_loss_diff": fu["market_vs_production"]["log_loss_diff"],
        "log_loss_diff_ci": fu["market_vs_production"]["log_loss_diff_ci95_weekly"],
        "per_league": {
            code: {
                "n_matches": x["n_matches"],
                "production_log_loss": x["production"]["log_loss"],
                "market_log_loss": x["market"]["log_loss"],
                "production_accuracy": x["production"]["accuracy"],
                "market_accuracy": x["market"]["accuracy"],
            }
            for code, x in part_a["per_league_follow_up"].items()
        },
        "value_flags": market.get("descriptive_value_flags", {}).get("follow_up", []),
    }


def _add_leagues(report: dict[str, Any], args: argparse.Namespace, first_preds: Any) -> None:
    """Score every league (same frozen production model) and replay the daily pick
    rule on the pooled test predictions of the verified ones."""
    from edge_ingestion.history import openfootball

    codes = _codes(args) if args.source == "openfootball" else ["football-data"]
    production = ModelParams()
    leagues: list[dict[str, Any]] = []
    pooled: dict[str, Any] = {
        "keys": [],
        "kickoffs": [],
        "probs": [],
        "outcomes": [],
        "prediction_times": [],
    }
    for idx, code in enumerate(codes):
        warnings: list[str] = []
        if idx == 0:
            preds, evaluation = first_preds, report["test"]
            n_total = report["data"]["n_matches"]
        else:
            matches = openfootball.load(
                args.first_season, args.last_season, args.cache_dir, code, warnings
            )
            cfg = BacktestConfig(
                eval_start=_season_start(matches, args.test_from), reference="production"
            )
            preds = walk_forward(
                matches,
                [
                    BaseRateForecaster(),
                    EloOnlyForecaster(),
                    ModelForecaster("production", production),
                ],
                cfg,
            )
            evaluation, n_total = evaluate(preds, cfg), len(matches)
        summary = league_summary(code, evaluation, n_total)
        summary["data_warnings"] = warnings
        leagues.append(summary)
        logger.info(
            "%s: test n=%d production %.4f base %.4f verified=%s",
            code,
            summary["test_matches"],
            summary["models"]["production"]["log_loss"],
            summary["models"]["base_rate"]["log_loss"],
            summary["verified"],
        )
        if summary["verified"]:
            for k, m in enumerate(preds.matches):
                r = m.result
                pooled["keys"].append(f"{code}|{r.kickoff_at.isoformat()}|{r.home}|{r.away}")
                pooled["kickoffs"].append(r.kickoff_at)
                pooled["probs"].append(preds.probs["production"][k])
                pooled["outcomes"].append(preds.outcomes[k])
                pooled["prediction_times"].append(preds.fitted_at[k])
    report["leagues"] = leagues
    # Today's Pick rule replayed on the frozen test predictions (production model),
    # pooled over the verified leagues because the service picks across them.
    verified_codes = [lg["code"] for lg in leagues if lg["verified"]]

    def replay(decision_hour: int | None, day_start_hour: int = 0) -> list[dict[str, Any]]:
        if not pooled["keys"]:
            return []
        return backtest_daily_picks(
            pooled["keys"],
            pooled["kickoffs"],
            np.asarray(pooled["probs"]).reshape(-1, 3),
            np.asarray(pooled["outcomes"]),
            PICK_THRESHOLDS,
            decision_hour=decision_hour,
            prediction_times=pooled["prediction_times"] if decision_hour is not None else None,
            day_start_hour=day_start_hour,
        )

    report["daily_pick_backtest"] = {
        # every match of the local day is a candidate: overstates how often the
        # service (which decides at the publish hour) can publish a pick
        "evaluation_scope": "whole_day_not_live_replay",
        "model": "production",
        "tz": "Asia/Seoul",
        "leagues": verified_codes,
        "rows": replay(None),
    }
    report["daily_pick_timing_proxy"] = {
        # the service's rule: decided at PICK_PUBLISH_HOUR from the matches kicking
        # off between then and the same hour the next day
        "evaluation_scope": "timing_only_not_live_quality_replay",
        "selection_bias": "league scope selected on the same test results",
        "model": "production",
        "tz": "Asia/Seoul",
        "decision_hour": PICK_DECISION_HOUR,
        "window": "decision_hour_to_next_day_decision_hour",
        "leagues": verified_codes,
        "rows": replay(PICK_DECISION_HOUR, day_start_hour=PICK_DECISION_HOUR),
    }
    report["daily_pick_timing_proxy_until_midnight"] = {
        # the earlier service rule (until 2026-10-16): same decision hour, but
        # only matches before local midnight; kept for comparison
        "evaluation_scope": "timing_only_not_live_quality_replay",
        "model": "production",
        "tz": "Asia/Seoul",
        "decision_hour": PICK_DECISION_HOUR,
        "window": "decision_hour_to_midnight",
        "leagues": verified_codes,
        "rows": replay(PICK_DECISION_HOUR),
    }


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
