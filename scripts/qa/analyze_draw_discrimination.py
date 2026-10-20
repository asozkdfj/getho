"""Exploratory draw discrimination and model-market confidence decomposition."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from scripts.qa.analyze_paired_market import analyze, winner


def auc(probabilities, outcomes):
    positives = [p for p, y in zip(probabilities, outcomes, strict=True) if y]
    negatives = [p for p, y in zip(probabilities, outcomes, strict=True) if not y]
    if not positives or not negatives:
        return None
    return sum(
        (p > n) + 0.5 * (p == n) for p in positives for n in negatives
    ) / (len(positives) * len(negatives))


def draw_summary(rows):
    if not rows:
        return {"n": 0}
    outcomes = [r["outcome"] == 1 for r in rows]
    return {
        "n": len(rows),
        "draws": sum(outcomes),
        "draw_rate": sum(outcomes) / len(rows),
        **{
            model: {
                "mean_draw_probability": sum(r[model][1] for r in rows) / len(rows),
                "draw_brier": sum(
                    (r[model][1] - y) ** 2 for r, y in zip(rows, outcomes, strict=True)
                ) / len(rows),
                "draw_auc": auc([r[model][1] for r in rows], outcomes),
            }
            for model in ("production", "market")
        },
    }


def confidence_summary(rows):
    if not rows:
        return {"n": 0}
    return {
        "n": len(rows),
        "chosen_outcome_hit_rate": sum(
            winner(r["production"]) == r["outcome"] for r in rows
        ) / len(rows),
        "production_probability_of_chosen_outcome": sum(
            max(r["production"]) for r in rows
        ) / len(rows),
        "market_probability_of_same_chosen_outcome": sum(
            r["market"][winner(r["production"])] for r in rows
        ) / len(rows),
    }


def report(manifest):
    validated = analyze(manifest)
    rows = [r for r in manifest if r["pair_eligible"] and r["outcome"] is not None]
    bins = {}
    for low, high in ((0, 0.2), (0.2, 0.25), (0.25, 0.3), (0.3, 1.000001)):
        bins[f"{low}_{high}"] = draw_summary([
            r for r in rows if low <= r["production"][1] < high
        ])
    excess = {}
    for low, high in ((-1, 0), (0, 0.05), (0.05, 0.1), (0.1, 1.000001)):
        excess[f"{low}_{high}"] = confidence_summary([
            r for r in rows if low <= max(r["production"])
            - r["market"][winner(r["production"])] < high
        ])
    contributions = {}
    for i, label in enumerate(("home", "draw", "away")):
        selected = [r for r in rows if r["outcome"] == i]
        delta_sum = sum(
            math.log(max(r["market"][i], 1e-15))
            - math.log(max(r["production"][i], 1e-15)) for r in selected
        )
        contributions[label] = {
            "n": len(selected),
            "within_outcome_mean_ll_delta": delta_sum / len(selected) if selected else None,
            "contribution_to_overall_ll_delta": delta_sum / len(rows) if rows else None,
        }
    return {
        "status": "EXPLORATORY_ONLY_NO_POLICY_CHANGE",
        "all": draw_summary(rows),
        "draw_bins_by_production_probability": bins,
        "confidence_excess_bins": excess,
        "ll_delta_production_minus_market_by_actual_outcome": contributions,
        "by_decision": {
            day: draw_summary([r for r in rows if r["decision"] == day])
            for day in sorted({r["decision"] for r in rows})
        },
        "high_confidence_60plus": draw_summary([
            r for r in rows if max(r["production"]) >= 0.6
        ]),
        "limitations": validated["limitations"] + [
            "Two decision days, one week; no confidence intervals or significance claims.",
            "Outcome-conditioned LL decomposition is retrospective, not a selection rule.",
            "AUC measures ranking, not calibration or profit.",
            "Bins are exploratory, not preregistered; no causal feature attribution.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    result = report([json.loads(line) for line in raw.decode("utf-8").splitlines() if line])
    result["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    result["analysis_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
