from datetime import UTC, datetime
from decimal import Decimal

import pytest

from edge_api.db.models import ModelVersion, OddsSnapshot, Prediction
from edge_api.services.analysis import analyse_outcomes, build_prediction_out

T = datetime(2026, 10, 15, 9, tzinfo=UTC)


def _prediction() -> Prediction:
    snap = OddsSnapshot(
        id=7,
        fixture_id=1,
        provider="mock",
        bookmaker="mockbook",
        market="1X2",
        odds_home=Decimal("2.10"),
        odds_draw=Decimal("3.40"),
        odds_away=Decimal("3.60"),
        captured_at=T,
    )
    mv = ModelVersion(
        id=1,
        name="m",
        version="0.1.0",
        git_sha="abc",
        feature_set="fs",
        calibration="identity",
        params={},
    )
    return Prediction(
        id=3,
        fixture_id=1,
        model_version_id=1,
        market_odds_snapshot_id=7,
        created_at=T,
        input_data_as_of=T,
        probability_home=0.50,
        probability_draw=0.27,
        probability_away=0.23,
        expected_goals_home=1.6,
        expected_goals_away=1.0,
        features={},
        odds_snapshot=snap,
        model_version=mv,
    )


def test_outcome_analysis_values():
    p = _prediction()
    rows = analyse_outcomes(p, p.odds_snapshot, threshold=0.03)
    home = rows[0]
    fair_home = (1 / 2.10) / (1 / 2.10 + 1 / 3.40 + 1 / 3.60)
    assert home.fair_probability == pytest.approx(fair_home)
    assert home.edge == pytest.approx(0.50 - fair_home)
    assert home.expected_value == pytest.approx(0.50 * 2.10 - 1)
    assert home.exceeds_threshold  # edge ~0.046, EV 0.05
    assert not rows[2].exceeds_threshold  # away: model below market
    assert sum(r.fair_probability for r in rows) == pytest.approx(1.0)


def test_build_prediction_out():
    out = build_prediction_out(_prediction(), threshold=0.03)
    assert out.market_odds_snapshot.id == 7
    assert out.overround == pytest.approx(1 / 2.1 + 1 / 3.4 + 1 / 3.6 - 1)
    assert out.devig_method == "proportional"
    assert out.model.version == "0.1.0"
