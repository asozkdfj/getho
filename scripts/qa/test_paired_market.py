from datetime import UTC, datetime, timedelta

import pytest

from scripts.qa.analyze_paired_market import analyze, paired


def row(i=0):
    return {
        "id": i,
        "decision": (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(weeks=i)).isoformat(),
        "league_id": 1,
        "pair_eligible": True,
        "outcome": 0,
        "exclusions": [],
        "production": [0.5, 0.25, 0.25],
        "market": [0.7, 0.15, 0.15],
        "blend_25": [0.65, 0.175, 0.175],
        "absence_teams": 0,
        "lineup_teams": 0,
    }


def test_pairing_sign_and_low_week_guard():
    result = analyze([row()])
    p = result["paired"]["market_vs_production"]
    assert p["delta_log_loss_candidate_minus_baseline"] < 0
    assert p["weekly_bootstrap_95_ci"] is None
    assert result["paired"]["blend_25_vs_market"]["delta_log_loss_candidate_minus_baseline"] > 0


def test_cluster_interval_and_reproducibility():
    rows = [row(i) for i in range(8)]
    first = paired(rows, "market")
    assert first == paired(rows, "market")
    assert first["weekly_bootstrap_95_ci"][1] < 0
    assert paired(rows, "market", "market")["weekly_bootstrap_95_ci"] == [0.0, 0.0]


def test_reject_duplicates_invalid_probabilities_and_weight_drift():
    with pytest.raises(ValueError, match="duplicate"):
        analyze([row(), row()])
    r = row()
    r["market"] = [float("nan"), 0.2, 0.3]
    with pytest.raises(ValueError, match="probabilities"):
        analyze([r])
    r = row()
    r["blend_25"] = r["market"]
    with pytest.raises(ValueError, match="fixed"):
        analyze([r])


def test_unsettled_excluded_and_empty_are_not_hits():
    unsettled = row(1)
    unsettled["outcome"] = None
    excluded = row(2)
    excluded.update(pair_eligible=False, exclusions=["missing"])
    result = analyze([row(), unsettled, excluded])
    assert result["settled_pairs"] == 1
    assert result["eligible_unsettled"] == 1
    assert result["excluded"] == 1
    assert analyze([])["metrics"]["market"] is None
