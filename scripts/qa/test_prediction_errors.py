import pytest

from scripts.qa.analyze_prediction_errors import report


def row(identifier, production, market, outcome):
    return {
        "id": identifier, "decision": "2026-10-17T00:00:00+00:00",
        "league_id": 1, "pair_eligible": True, "outcome": outcome, "exclusions": [],
        "production": production, "market": market,
        "blend_25": [0.25 * p + 0.75 * m for p, m in zip(production, market, strict=True)],
        "absence_teams": 0, "lineup_teams": 0,
    }


def test_shared_draw_failure_and_disagreement_are_not_market_wins():
    result = report([
        row(1, [0.7, 0.2, 0.1], [0.6, 0.3, 0.1], 1),
        row(2, [0.6, 0.1, 0.3], [0.3, 0.1, 0.6], 2),
    ])
    agree = result["slices"]["agree"]
    assert agree["failure_outcomes_home_draw_away"] == [0, 1, 0]
    assert agree["market_correct_on_production_failures"] == 0
    assert result["slices"]["disagree"]["market"]["accuracy"] == 1
    assert result["slices"]["production_confidence_0.6_0.7"]["n"] == 1
    assert result["slices"]["production_confidence_0.7_1.000001"]["n"] == 1
    assert result["slices"]["all"]["production_minus_market"]["weekly_bootstrap_95_ci"] is None


def test_duplicate_rejected_and_empty_supported():
    item = row(1, [0.7, 0.2, 0.1], [0.6, 0.3, 0.1], 1)
    with pytest.raises(ValueError, match="duplicate"):
        report([item, item])
    assert report([])["slices"]["all"] == {"n": 0}
