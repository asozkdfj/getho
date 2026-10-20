import pytest

from scripts.qa.analyze_historical_errors import analyze, validate


def fixture(season="2023-24"):
    return {
        "league": "en.1", "season": season, "kickoff_at": "2023-08-01T12:00:00+00:00",
        "home": "A", "away": "B", "outcome": 1,
        "production": [0.6, 0.3, 0.1], "market_only": [0.2, 0.3, 0.5],
    }


def test_window_selection_and_disagreement():
    result = analyze([fixture(), fixture("2022-23")])
    assert result["follow_up_rows"] == 1
    assert result["overall"]["disagree"]["n"] == 1
    assert result["overall"]["draw"]["draws"] == 1
    assert result["overall"]["disagree"]["production"]["accuracy"] == 0
    assert result["overall"]["disagree"]["market"]["accuracy"] == 0


def test_bad_probabilities_duplicates_and_rounding():
    item = fixture()
    with pytest.raises(ValueError, match="duplicate"):
        validate([item, item])
    item["production"] = [0.600001, 0.3, 0.1]
    validate([item])
    item["production"] = [float("nan"), 0.3, 0.1]
    with pytest.raises(ValueError, match="probability"):
        validate([item])
