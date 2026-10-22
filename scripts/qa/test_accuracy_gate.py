from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from scripts.qa.analyze_accuracy_gate import DRAWS, SEED, paired_accuracy


def rows_by_week():
    rows = []
    for week in range(10):
        for _ in range(week + 1):
            rows.append(
                {
                    "kickoff_at": (
                        datetime(2025, 1, 6, tzinfo=UTC) + timedelta(weeks=week)
                    ).isoformat(),
                    "outcome": 0,
                    "production": [0.7, 0.2, 0.1] if week % 2 else [0.1, 0.2, 0.7],
                    "candidate": [0.1, 0.2, 0.7] if week % 2 else [0.7, 0.2, 0.1],
                }
            )
    return rows


def test_paired_blocks_are_match_weighted_and_direction_reversible():
    rows = rows_by_week()
    result = paired_accuracy(rows, "candidate")
    blocks = [[(-1 if w % 2 else 1)] * (w + 1) for w in range(10)]
    rng = np.random.default_rng(SEED)
    means = []
    for _ in range(DRAWS):
        expanded = [v for w in rng.integers(0, 10, 10) for v in blocks[w]]
        means.append(sum(expanded) / len(expanded))
    assert result["weekly_paired_95_ci"] == pytest.approx(np.quantile(means, [0.025, 0.975]))
    assert result["accuracy_delta"] == pytest.approx(-5 / 55)
    reverse = paired_accuracy(rows, "production", "candidate")
    assert reverse["weekly_paired_95_ci"] == pytest.approx(
        [-x for x in reversed(result["weekly_paired_95_ci"])]
    )


def test_noninferiority_does_not_imply_improvement():
    rows = rows_by_week()
    for row in rows:
        row["candidate"] = row["production"]
    result = paired_accuracy(rows, "candidate")
    assert result["illustrative_noninferiority_lower_gt_minus_001"]
    assert not result["illustrative_improvement_lower_gt_zero"]
    assert paired_accuracy(rows[:1], "candidate")["weekly_paired_95_ci"] is None
    with pytest.raises(ValueError, match="empty"):
        paired_accuracy([], "candidate")
    rows[0]["kickoff_at"] = "2025-01-06"
    with pytest.raises(ValueError, match="timezone"):
        paired_accuracy(rows, "candidate")
