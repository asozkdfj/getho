"""Descriptive accuracy intervals on already examined predictions; no adoption gate."""

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from scripts.qa.analyze_paired_market import winner
from scripts.qa.analyze_xg_complementarity import analyze

SEED = 20261022
DRAWS = 4000


def paired_accuracy(rows, candidate, baseline="production"):
    if not rows:
        raise ValueError("empty sample")
    groups = defaultdict(list)
    corrected = introduced = 0
    for row in rows:
        at = datetime.fromisoformat(row["kickoff_at"])
        if at.tzinfo is None:
            raise ValueError("timezone required")
        iso = at.astimezone(UTC).isocalendar()
        c = int(winner(row[candidate]) == row["outcome"])
        b = int(winner(row[baseline]) == row["outcome"])
        groups[(iso.year, iso.week)].append(c - b)
        corrected += c > b
        introduced += c < b
    totals = np.array([[sum(v), len(v)] for _, v in sorted(groups.items())])
    ci = None
    if len(totals) >= 8:  # descriptive reporting guard, not an approved minimum sample
        indices = np.random.default_rng(SEED).integers(0, len(totals), size=(DRAWS, len(totals)))
        sampled = totals[indices].sum(axis=1)
        ci = np.quantile(sampled[:, 0] / sampled[:, 1], [0.025, 0.975]).tolist()
    return {
        "n": len(rows),
        "utc_kickoff_weeks": len(groups),
        "corrected": corrected,
        "introduced": introduced,
        "accuracy_delta": (corrected - introduced) / len(rows),
        "weekly_paired_95_ci": ci,
        "illustrative_noninferiority_lower_gt_minus_001": ci[0] > -0.01 if ci else None,
        "illustrative_improvement_lower_gt_zero": ci[0] > 0 if ci else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.predictions.read_bytes()
    rows = [json.loads(line) for line in gzip.decompress(raw).decode().splitlines()]
    analyze(rows)  # shared probability, outcome and fixture uniqueness validation
    result = {
        "status": "DESCRIPTIVE_ONLY_NOT_AVAILABILITY_CANDIDATE_OR_PROMOTION",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "seed": SEED,
        "draws": DRAWS,
        "blocks": "UTC ISO kickoff week; decision timestamp unavailable; timing proxy",
        "tie_break": "HOME, AWAY, DRAW (existing QA convention; preregister for new study)",
        "segments": {
            season: {
                candidate: paired_accuracy([r for r in rows if r["season"] == season], candidate)
                for candidate in ("sot_and_finishing", "sot_finishing_plus_xg")
            }
            for season in ("2024-25", "2025-26")
        },
        "limitations": [
            "Already examined periods and candidates; no untouched holdout.",
            "No source training replay or availability candidate predictions.",
            "Illustrations are not adoption decisions; LL/Brier gates still apply.",
            "Eight-week guard is not a power calculation; zero discordance is degenerate.",
        ],
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8", newline="\n")
    print(json.dumps(result["segments"]))


if __name__ == "__main__":
    main()
