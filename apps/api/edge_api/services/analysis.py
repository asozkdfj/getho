"""Turn a stored prediction + its odds snapshot into market comparison metrics.

Derived numbers (fair probability, edge, EV) are recomputed from the immutable
snapshot rows, so they are always reproducible from the database.
"""

from __future__ import annotations

from edge_api.db.models import OddsSnapshot, Prediction
from edge_api.schemas import (
    ExpectedGoalsOut,
    ModelVersionOut,
    OddsSnapshotOut,
    OutcomeAnalysisOut,
    PredictionOut,
    ProbabilitiesOut,
)
from edge_ml.core import Outcome, Probabilities1X2
from edge_ml.market import MarketView, market_view_1x2
from edge_ml.value import edge, exceeds_threshold, expected_value


def market_view(snapshot: OddsSnapshot) -> MarketView:
    return market_view_1x2(
        float(snapshot.odds_home), float(snapshot.odds_draw), float(snapshot.odds_away)
    )


def model_probabilities(prediction: Prediction) -> Probabilities1X2:
    return Probabilities1X2(
        prediction.probability_home, prediction.probability_draw, prediction.probability_away
    )


def to_probabilities_out(p: Probabilities1X2) -> ProbabilitiesOut:
    return ProbabilitiesOut(home=p.home, draw=p.draw, away=p.away)


def odds_for(snapshot: OddsSnapshot, outcome: Outcome) -> float:
    return float(
        {
            Outcome.HOME: snapshot.odds_home,
            Outcome.DRAW: snapshot.odds_draw,
            Outcome.AWAY: snapshot.odds_away,
        }[outcome]
    )


def analyse_outcomes(
    prediction: Prediction, snapshot: OddsSnapshot, threshold: float
) -> list[OutcomeAnalysisOut]:
    mv = market_view(snapshot)
    model_p = model_probabilities(prediction)
    rows = []
    for i, outcome in enumerate(Outcome):
        odds = odds_for(snapshot, outcome)
        p_model = model_p.get(outcome)
        p_fair = mv.fair.get(outcome)
        e = edge(p_model, p_fair)
        ev = expected_value(p_model, odds)
        rows.append(
            OutcomeAnalysisOut(
                outcome=outcome,
                decimal_odds=odds,
                implied_probability=mv.implied_raw[i],
                fair_probability=p_fair,
                model_probability=p_model,
                edge=e,
                expected_value=ev,
                exceeds_threshold=exceeds_threshold(e, ev, threshold),
            )
        )
    return rows


def build_prediction_out(prediction: Prediction, threshold: float) -> PredictionOut:
    snapshot = prediction.odds_snapshot
    mv = market_view(snapshot)
    return PredictionOut(
        prediction_id=prediction.id,
        fixture_id=prediction.fixture_id,
        created_at=prediction.created_at,
        input_data_as_of=prediction.input_data_as_of,
        model=ModelVersionOut.model_validate(prediction.model_version),
        market_odds_snapshot=OddsSnapshotOut.model_validate(snapshot),
        probabilities=to_probabilities_out(model_probabilities(prediction)),
        fair_market_probabilities=to_probabilities_out(mv.fair),
        overround=mv.overround,
        devig_method=mv.method.value,
        expected_goals=ExpectedGoalsOut(
            home=prediction.expected_goals_home, away=prediction.expected_goals_away
        ),
        outcomes=analyse_outcomes(prediction, snapshot, threshold),
        value_threshold=threshold,
        features=prediction.features,
    )
