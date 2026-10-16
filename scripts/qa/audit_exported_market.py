"""Recalculate exported market predictions, not a raw-data model retraining."""

import argparse
import gzip
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.repository / "ml/reports/backtest-market.predictions.jsonl.gz"
    report = json.loads((args.repository / "ml/reports/backtest-market.json").read_text("utf-8"))
    with gzip.open(artifact, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    keys = [(r["league"], r["kickoff_at"], r["home"], r["away"]) for r in rows]
    assert len(keys) == len(set(keys))
    names = ["production", "market_only", "blend_w0.25", "blend_w0.50", "blend_w0.75"]
    for row in rows:
        assert row["outcome"] in (0, 1, 2)
        for name in names:
            p = row[name]
            assert len(p) == 3 and all(math.isfinite(v) and 0 <= v <= 1 for v in p)
            assert abs(sum(p) - 1) < 2e-6  # export rounds each of 3 values to 6 decimals
    result = {
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "rows": len(rows),
    }
    for segment, seasons in (
        ("validation", {"2020-21", "2021-22", "2022-23"}),
        ("follow_up", {"2023-24", "2024-25", "2025-26"}),
    ):
        sample = [r for r in rows if r["season"] in seasons]
        n = len(sample)
        metrics = {}
        for name in names:
            metrics[name] = {
                "log_loss": sum(-math.log(r[name][r["outcome"]]) for r in sample) / n,
                "brier": sum(
                    sum((v - (i == r["outcome"])) ** 2 for i, v in enumerate(r[name]))
                    for r in sample
                )
                / n,
                "accuracy": sum(
                    max(range(3), key=lambda i: r[name][i]) == r["outcome"] for r in sample
                )
                / n,
            }
        for name, reference in (("production", "production"), ("market_only", "market")):
            expected = report["part_a_model_vs_market"][segment][reference]
            assert abs(metrics[name]["log_loss"] - expected["log_loss"]) < 1e-6
        tiers = []
        for lo, hi in ((0.65, 1.01), (0.55, 0.65)):
            part = [r for r in sample if lo <= max(r["production"]) < hi]
            tiers.append(
                {
                    "lower": lo,
                    "n": len(part),
                    "accuracy": sum(
                        max(range(3), key=lambda i: r["production"][i]) == r["outcome"]
                        for r in part
                    )
                    / len(part),
                }
            )
        result[segment] = {"n": n, "metrics": metrics, "tiers": tiers}
    result["fitted_at_or_after_kickoff"] = sum(
        datetime.fromisoformat(r["fitted_at"]) >= datetime.fromisoformat(r["kickoff_at"])
        for r in rows
    )
    result["fitted_at_strictly_after_kickoff"] = sum(
        datetime.fromisoformat(r["fitted_at"]) > datetime.fromisoformat(r["kickoff_at"])
        for r in rows
    )
    result["reported_gate"] = report["gate"]
    result["limitations"] = [
        "Exported predictions only; source data and model fitting not rerun",
        "No observed market capture time, prediction availability or complete exclusion manifest",
        "Research gate is not approval for 09:00 KST production promotion",
    ]
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
