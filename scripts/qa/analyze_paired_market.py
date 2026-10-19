"""Descriptive paired analysis of the frozen decision-market audit manifest.

No fitting, weight selection, live API calls, or promotion decisions.
"""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from scripts.qa.audit_decision_market import metrics, valid_probabilities

MODELS = ("production", "market", "blend_25")


def winner(p):
    return max((0, 2, 1), key=lambda i: p[i])


def week(row):
    iso = datetime.fromisoformat(row["decision"]).isocalendar()
    return f"{iso.year}-W{iso.week:02}"


def paired(rows, candidate, baseline="production"):
    differences = [
        -math.log(max(r[candidate][r["outcome"]], 1e-15))
        + math.log(max(r[baseline][r["outcome"]], 1e-15))
        for r in rows
    ]
    clusters = defaultdict(list)
    for r, delta in zip(rows, differences, strict=True):
        clusters[week(r)].append(delta)
    ci = None
    # A reporting guard, NOT a replacement for the registered adoption gate.
    if len(clusters) >= 8:
        totals = np.array([[sum(v), len(v)] for _, v in sorted(clusters.items())])
        indices = np.random.default_rng(20261019).integers(0, len(totals), size=(4000, len(totals)))
        draws = totals[indices].sum(axis=1)
        ci = np.quantile(draws[:, 0] / draws[:, 1], [0.025, 0.975]).tolist()
    return {
        "n": len(rows),
        "delta_log_loss_candidate_minus_baseline": (
            sum(differences) / len(differences) if differences else None
        ),
        "candidate_better_games": sum(d < -1e-12 for d in differences),
        "baseline_better_games": sum(d > 1e-12 for d in differences),
        "tied_games": sum(abs(d) <= 1e-12 for d in differences),
        "decision_weeks": len(clusters),
        "weekly_bootstrap_95_ci": ci,
        "ci_status": "descriptive_only" if ci else "insufficient_weeks_minimum_8",
    }


def calibration(rows, model):
    bins = []
    for i in range(10):
        selected = [r for r in rows if min(int(max(r[model]) * 10), 9) == i]
        bins.append(
            {
                "lower": i / 10,
                "upper": (i + 1) / 10,
                "n": len(selected),
                "confidence": sum(max(r[model]) for r in selected) / len(selected)
                if selected
                else None,
                "accuracy": metrics(selected, model)["accuracy"] if selected else None,
            }
        )
    return {
        "bins": bins,
        "top_label_ece": (
            sum(b["n"] * abs(b["confidence"] - b["accuracy"]) for b in bins if b["n"]) / len(rows)
            if rows
            else None
        ),
    }


def analyze(manifest):
    keys = [(r["id"], r["decision"]) for r in manifest]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate fixture/decision")
    rows = [r for r in manifest if r["pair_eligible"] and r["outcome"] is not None]
    for r in rows:
        if r["outcome"] not in (0, 1, 2) or r["exclusions"]:
            raise ValueError("invalid eligibility or outcome")
        for model in MODELS:
            if not valid_probabilities(r[model]):
                raise ValueError("invalid probabilities")
        expected = [0.25 * p + 0.75 * m for p, m in zip(r["production"], r["market"], strict=True)]
        if any(abs(a - b) > 1e-12 for a, b in zip(expected, r["blend_25"], strict=True)):
            raise ValueError("blend must remain fixed at 25 percent production")
    groups = {}
    for key in ("league_id", "decision"):
        groups[key] = {
            str(value): {m: metrics([r for r in rows if r[key] == value], m) for m in MODELS}
            for value in sorted({r[key] for r in rows})
        }
    return {
        "status": "DESCRIPTIVE_ONLY_NOT_PROMOTION_EVIDENCE",
        "manifest_count": len(manifest),
        "settled_pairs": len(rows),
        "eligible_unsettled": sum(r["pair_eligible"] and r["outcome"] is None for r in manifest),
        "excluded": sum(not r["pair_eligible"] for r in manifest),
        "exclusions_nonexclusive": dict(Counter(x for r in manifest for x in r["exclusions"])),
        "metrics": {m: metrics(rows, m) for m in MODELS},
        "paired": {
            f"{c}_vs_{b}": paired(rows, c, b)
            for c, b in (
                ("market", "production"),
                ("blend_25", "production"),
                ("blend_25", "market"),
            )
        },
        "calibration": {m: calibration(rows, m) for m in MODELS},
        "segments": groups,
        "information_coverage_in_settled_pairs": {
            k: sum(r[k] == 2 for r in rows) for k in ("absence_teams", "lineup_teams")
        },
        "confidence_60_percent_descriptive_not_daily_pick": {
            m: {
                "coverage": sum(max(r[m]) >= 0.6 for r in rows) / len(rows) if rows else None,
                "metrics": metrics([r for r in rows if max(r[m]) >= 0.6], m),
            }
            for m in MODELS
        },
        "parameters": {
            "production_weight": 0.25,
            "bootstrap_seed": 20261019,
            "bootstrap_draws": 4000,
            "minimum_weeks_for_reporting_ci": 8,
        },
        "limitations": [
            "Inherited timing/source limitations; no independent availability certification",
            "Current schedule/results are not frozen decision-time candidate sets",
            "No season identifier: season comparison and cross-season stability unavailable",
            "No fatigue/player candidate predictions: incremental feature performance not measured",
            "Subgroups and confidence threshold are descriptive, not model selection evidence",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    report = analyze([json.loads(line) for line in raw.decode("utf-8").splitlines() if line])
    report["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    report["analysis_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "settled_pairs",
                    "metrics",
                    "paired",
                    "information_coverage_in_settled_pairs",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
