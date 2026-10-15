from edge_api.db.models import Prediction
from edge_api.services.highlights import caveats_for


def _prediction(**features) -> Prediction:
    return Prediction(features=features)


def test_caveats_flag_promoted_teams_and_large_gaps():
    p = _prediction(prior_home="promoted_relegation_level", prior_away="data")
    assert caveats_for(p, 0.04) == ["promoted_home"]
    p = _prediction(prior_home="data", prior_away="unseen_relegation_level")
    assert caveats_for(p, 0.12) == ["promoted_away", "large_gap"]
    assert caveats_for(_prediction(prior_home="data", prior_away="data"), 0.05) == []


def test_caveats_tolerate_v010_predictions_without_prior_features():
    assert caveats_for(_prediction(elo_home=1500), 0.03) == []
