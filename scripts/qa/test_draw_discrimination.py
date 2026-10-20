import math

import pytest

from scripts.qa.analyze_draw_discrimination import auc, report
from scripts.qa.test_prediction_errors import row


def test_auc_ties_and_single_class():
    assert auc([0.9, 0.1], [True, False]) == 1
    assert auc([0.1, 0.9], [True, False]) == 0
    assert auc([0.5, 0.5], [True, False]) == 0.5
    assert auc([0.5], [True]) is None


def test_same_event_comparison_and_ll_decomposition():
    rows = [
        row(1, [0.6, 0.25, 0.15], [0.3, 0.2, 0.5], 1),
        row(2, [0.3, 0.2, 0.5], [0.4, 0.2, 0.4], 2),
    ]
    result = report(rows)
    group = result["confidence_excess_bins"]["0.1_1.000001"]
    assert group["market_probability_of_same_chosen_outcome"] == 0.3
    assert result["draw_bins_by_production_probability"]["0.25_0.3"]["n"] == 1
    actual = sum(
        v["contribution_to_overall_ll_delta"]
        for v in result["ll_delta_production_minus_market_by_actual_outcome"].values()
    )
    expected = sum(math.log(r["market"][r["outcome"]] / r["production"][r["outcome"]])
                   for r in rows) / 2
    assert actual == pytest.approx(expected)
    assert report([])["all"] == {"n": 0}
