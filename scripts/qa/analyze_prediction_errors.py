"""Exploratory error slices of the frozen paired manifest; no policy fitting."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.qa.analyze_paired_market import analyze, metrics, paired, winner


def summarize(rows):
    if not rows:
        return {"n": 0}
    failures = [r for r in rows if winner(r["production"]) != r["outcome"]]
    return {
        "n": len(rows),
        "production": metrics(rows, "production"),
        "market": metrics(rows, "market"),
        "production_minus_market": paired(rows, "production", "market"),
        "production_mean_confidence": sum(max(r["production"]) for r in rows) / len(rows),
        "production_failures": len(failures),
        "failure_outcomes_home_draw_away": [
            sum(r["outcome"] == i for r in failures) for i in range(3)
        ],
        "market_correct_on_production_failures": sum(
            winner(r["market"]) == r["outcome"] for r in failures
        ),
    }


def report(manifest):
    validated = analyze(manifest)  # Reuse strict eligibility/probability validation.
    rows = [r for r in manifest if r["pair_eligible"] and r["outcome"] is not None]
    slices = {
        "all": rows,
        "agree": [r for r in rows if winner(r["production"]) == winner(r["market"])],
        "disagree": [r for r in rows if winner(r["production"]) != winner(r["market"])],
    }
    for low, high in ((0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.000001)):
        slices[f"production_confidence_{low}_{high}"] = [
            r for r in rows if low <= max(r["production"]) < high
        ]
    for label, outcome in (("home", 0), ("draw", 1), ("away", 2)):
        slices[f"production_top_{label}"] = [
            r for r in rows if winner(r["production"]) == outcome
        ]
        slices[f"production_top_{label}_60plus"] = [
            r for r in rows if winner(r["production"]) == outcome
            and max(r["production"]) >= 0.6
        ]
    for low, high in ((-1, 0), (0, 0.05), (0.05, 0.1), (0.1, 1.000001)):
        slices[f"confidence_excess_over_market_{low}_{high}"] = [
            r for r in rows
            if low <= r["production"][winner(r["production"])]
            - r["market"][winner(r["production"])] < high
        ]
    return {
        "status": "EXPLORATORY_NOT_PROFIT_OR_PROMOTION_EVIDENCE",
        "manifest_count": len(manifest),
        "settled_pairs": len(rows),
        "decision_counts": dict(Counter(r["decision"] for r in rows)),
        "outcome_rates_and_mean_probabilities": {
            label: {
                "observed": sum(r["outcome"] == i for r in rows) / len(rows) if rows else None,
                **{
                    model: sum(r[model][i] for r in rows) / len(rows) if rows else None
                    for model in ("production", "market")
                },
            }
            for i, label in enumerate(("home", "draw", "away"))
        },
        "tie_policy": "home then away then draw; inherited",
        "slices": {name: summarize(group) for name, group in slices.items()},
        "by_decision": {
            date: summarize([r for r in slices["disagree"] if r["decision"] == date])
            for date in sorted({r["decision"] for r in rows})
        },
        "limitations": validated["limitations"] + [
            "Bins specified for exploration, not preregistered confirmatory tests.",
            "Only two decision dates and one week; no reliable subgroup inference.",
            "No Betman odds or real ticket history: no ROI or last-leg claim.",
            "Association of failures is not causal attribution to injuries or tactics.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    result = report([json.loads(line) for line in raw.decode("utf-8").splitlines() if line])
    result["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    result["analysis_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for name, group in result["slices"].items():
        print(name, json.dumps(group))


if __name__ == "__main__":
    main()
