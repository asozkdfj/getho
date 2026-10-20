"""Replay error diagnostics on saved market predictions, without retraining."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

from scripts.qa.analyze_draw_discrimination import confidence_summary, draw_summary
from scripts.qa.analyze_paired_market import winner
from scripts.qa.analyze_prediction_errors import summarize


def validate(rows):
    keys = [(r["league"], r["season"], r["kickoff_at"], r["home"], r["away"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate fixture")
    for r in rows:
        if r["outcome"] not in (0, 1, 2):
            raise ValueError("invalid outcome")
        for model in ("production", "market_only"):
            p = r[model]
            if len(p) != 3 or any(not math.isfinite(x) or x < 0 or x > 1 for x in p):
                raise ValueError("invalid probability")
            if abs(sum(p) - 1) > 2e-6:
                raise ValueError("invalid probability sum")


def analyze(rows):
    validate(rows)
    selected = [
        dict(r, market=r["market_only"], decision=r["kickoff_at"])
        for r in rows if r["season"] in ("2023-24", "2024-25", "2025-26")
    ]
    def group(items):
        disagree = [r for r in items if winner(r["production"]) != winner(r["market"])]
        high = [r for r in items if max(r["production"]) >= 0.6]
        excess = [r for r in items if max(r["production"])
                  - r["market"][winner(r["production"])] >= 0.1]
        return {
            "all": summarize(items), "draw": draw_summary(items),
            "disagree": summarize(disagree), "high_confidence": draw_summary(high),
            "excess_10pp": confidence_summary(excess),
        }
    return {
        "status": "EXPLORATORY_SAVED_PREDICTIONS_NOT_NEW_HOLDOUT",
        "input_rows": len(rows), "follow_up_rows": len(selected),
        "overall": group(selected),
        "by_season": {
            s: group([r for r in selected if r["season"] == s])
            for s in sorted({r["season"] for r in selected})
        },
        "limitations": [
            "Saved six-decimal probabilities; rounding tolerance 2e-6, no renormalization.",
            "Market odds availability time unknown; not a same-decision comparison.",
            "Weekly clusters use kickoff week, not actual decision week.",
            "Paired bootstrap: 4000 draws, seed 20261019; no multiplicity adjustment.",
            "Repeatedly explored 2023-26 period; not independent prospective confirmation.",
            "No training/source-data replay, Betman odds, ROI, or causal attribution.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.predictions.read_bytes()
    result = analyze([json.loads(line) for line in gzip.decompress(raw).decode().splitlines()])
    result["existing_experiment_inventory"] = {}
    for name in ("draws", "standings", "shots", "market", "calibration",
                 "fatigue-england", "lineups-statsbomb"):
        path = args.predictions.parent / f"backtest-{name}.json"
        content = path.read_bytes()
        existing = json.loads(content)
        result["existing_experiment_inventory"][name] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "generated_at": existing.get("generated_at"),
            "gate": existing.get("gate"),
            "standard_gate": existing.get("standard_gate"),
            "adopt": existing.get("adopt"),
        }
    result["predictions_sha256"] = hashlib.sha256(raw).hexdigest()
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
