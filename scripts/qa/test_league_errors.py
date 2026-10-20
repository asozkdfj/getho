import pytest

from scripts.qa.analyze_league_errors import analyze
from scripts.qa.test_historical_errors import fixture


def test_league_partition_and_weighting():
    first = fixture()
    second = dict(fixture(), league="en.2", outcome=2)
    third = dict(second, home="C")
    result = analyze([first, second, third, fixture("2022-23")])
    groups = result["by_league"]
    key = "delta_log_loss_candidate_minus_baseline"
    a, b = (groups[k]["paired"][key] for k in ("en.1", "en.2"))
    assert result["n"] == 3
    assert groups["en.1"]["n"] == 1
    assert groups["en.2"]["n"] == 2
    assert result["equal_league_weight_ll_delta"] == pytest.approx((a + b) / 2)
    assert result["fixture_weighted_ll_delta"] == pytest.approx((a + 2 * b) / 3)
    assert result["by_league_season"]["en.2"]["2023-24"]["n"] == 2
    assert analyze([])["equal_league_weight_ll_delta"] is None
