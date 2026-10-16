"""Audit committed evaluation summaries; does not rerun the full backtest.

Run from any directory with the project's numpy/scipy dependencies available:
    python scripts/qa/audit_model_v020.py --out docs/qa/model-v020-audit-summary.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))


def load_report(name: str) -> tuple[dict, dict]:
    path = ROOT / "ml" / "reports" / name
    data = path.read_bytes()
    return json.loads(data), {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def publication_probe() -> dict:
    """Synthetic counterexample to equivalence with the 09:00 candidate set."""
    import numpy as np

    from edge_ml.core import Probabilities1X2
    from edge_ml.picks import PickCandidate, backtest_daily_picks, select_pick

    zone = ZoneInfo("Asia/Seoul")
    kickoffs = [
        datetime(2026, 10, 16, 2, tzinfo=zone),
        datetime(2026, 10, 16, 20, tzinfo=zone),
    ]
    publish_at = datetime(2026, 10, 16, 9, tzinfo=zone)
    keys = ["already-started-at-publication", "upcoming-at-publication"]
    probs = np.array([[0.90, 0.05, 0.05], [0.20, 0.20, 0.60]])
    candidates = [
        PickCandidate(key, kickoff, Probabilities1X2.normalized(*p))
        for key, kickoff, p in zip(keys, kickoffs, probs, strict=True)
    ]
    historical = select_pick(candidates, 0.55)
    eligible = select_pick([c for c in candidates if c.kickoff_at > publish_at], 0.55)
    row = backtest_daily_picks(keys, kickoffs, probs, np.array([0, 0]), [0.55])[0]
    assert historical is not None and eligible is not None
    # This checks the real backtest function, rather than only the selector.
    assert row["mean_pick_probability"] == historical.probability
    return {
        "kind": "synthetic counterexample, not a performance estimate",
        "publication": publish_at.isoformat(),
        "historical_choice": historical.candidate.key,
        "historical_probability": historical.probability,
        "upcoming_only_choice": eligible.candidate.key,
        "upcoming_only_probability": eligible.probability,
        "candidate_sets_equivalent": historical.candidate.key == eligible.candidate.key,
        "other_quality_gates_reproduced": False,
    }


def audit() -> dict:
    report, source = load_report("backtest-openfootball.json")
    lineup, lineup_source = load_report("backtest-lineups-statsbomb.json")
    models = report["test"]["models"]
    prod, base = models["production"], models["base_rate"]
    leagues = report["leagues"]
    total = sum(lg["test_matches"] for lg in leagues)
    return {
        "sources": [source, lineup_source],
        "report_generated_at": report["generated_at"],
        "model_version": report["production"]["version"],
        "full_backtest_rerun": False,
        "epl": {
            "test_matches": report["test"]["n_matches"],
            "first_kickoff": report["test"]["first_kickoff"],
            "last_kickoff": report["test"]["last_kickoff"],
            "production": {
                "log_loss": prod["log_loss"],
                "brier": prod["brier"]["mean"],
                "accuracy": prod["accuracy"],
                "ece": prod["ece"],
            },
            "relative_log_loss_reduction_vs_base": (
                base["log_loss"]["mean"] - prod["log_loss"]["mean"]
            ) / base["log_loss"]["mean"],
            "accuracy_gain_vs_base_percentage_points": (
                prod["accuracy"] - base["accuracy"]
            ) * 100,
            "comparisons_other_minus_production": {
                name: models[name]["vs_reference"]["log_loss"]
                for name in (
                    "base_rate",
                    "elo_only",
                    "poisson_only",
                    "production_no_promoted_prior",
                )
            },
            "seasons": {
                season: {
                    **values,
                    "base_log_loss": base["per_season"][season]["log_loss"],
                    "relative_log_loss_reduction_vs_base": (
                        base["per_season"][season]["log_loss"] - values["log_loss"]
                    ) / base["per_season"][season]["log_loss"],
                }
                for season, values in prod["per_season"].items()
            },
        },
        "league_test_total": total,
        "weighted_league_accuracy": sum(
            lg["test_matches"] * lg["models"]["production"]["accuracy"] for lg in leagues
        ) / total,
        "leagues": [
            {
                "code": lg["code"],
                "test_matches": lg["test_matches"],
                "log_loss": lg["models"]["production"]["log_loss"],
                "elo_log_loss": lg["models"]["elo_only"]["log_loss"],
                "production_minus_elo": lg["models"]["production"]["log_loss"]
                - lg["models"]["elo_only"]["log_loss"],
                "data_warnings": lg["data_warnings"],
            }
            for lg in leagues
        ],
        "daily_pick_threshold_055": next(
            row for row in report["daily_pick_backtest"]["rows"] if row["min_probability"] == 0.55
        ),
        "publication_probe": publication_probe(),
        "lineup": {
            "fit": lineup["lineup_fit"],
            "promotion": lineup["promotion"],
            "per_league": lineup["per_league"],
            "sensitivity": lineup["sensitivity"],
            "report_adopt": lineup["adopt"],
            "statistical_significance_95pct": (
                lineup["promotion"]["checks"]["log_loss_diff_ci"][1] < 0
            ),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = audit()
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
        print(json.dumps(result["publication_probe"], ensure_ascii=False))
    else:
        print(text, end="")
