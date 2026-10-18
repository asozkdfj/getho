"""Independent calendar-time audit of PR #10's season-only split."""

import gzip
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from edge_ml.calibration import TopOutcomeCalibrator

repository = Path(sys.argv[1])
with gzip.open(repository / "ml/reports/backtest-market.predictions.jsonl.gz", "rt") as stream:
    rows = [json.loads(line) for line in stream]
seasons = sorted({r["season"] for r in rows})
timing = []
for season in seasons[1:]:
    train = [r for r in rows if r["season"] < season]
    target = [r for r in rows if r["season"] == season]
    last_result = max(datetime.fromisoformat(r["kickoff_at"]) for r in train) + timedelta(hours=3)
    premature = [r for r in target if datetime.fromisoformat(r["kickoff_at"]) < last_result]
    timing.append(
        {
            "season": season,
            "train_n": len(train),
            "target_n": len(target),
            "latest_training_result_proxy": last_result.isoformat(),
            "target_before_training_available": len(premature),
            "examples": [
                {k: r[k] for k in ("league", "season", "kickoff_at", "home", "away")}
                for r in premature[:3]
            ],
        }
    )
cal = TopOutcomeCalibrator("logistic").fit_arrays(
    [0.4, 0.5, 0.6, 0.7, 0.8] * 20, [1, 1, 0, 0, 0] * 20
)
mapped = cal.map_top(np.array([0.4, 0.8])).tolist()
print(
    json.dumps(
        {
            "calendar_audit": timing,
            "monotonic_counterexample": {
                "params": cal.params,
                "map_0.4_0.8": mapped,
                "nondecreasing": mapped[0] <= mapped[1],
            },
        },
        indent=2,
    )
)
