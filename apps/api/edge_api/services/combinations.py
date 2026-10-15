from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from edge_api.db.models import FixtureStatus
from edge_api.schemas import CombinationLegOut, CombinationOut, CombinationRequest, TeamOut
from edge_api.services.analysis import market_view, model_probabilities, odds_for
from edge_api.services.queries import get_fixture, latest_prediction
from edge_ml.combination import METHOD, Leg, combine
from edge_ml.value import edge, exceeds_threshold, expected_value

APPROXIMATION_NOTES = [
    "조합 확률은 각 경기 결과가 서로 독립이라고 가정한 근사치(independence approximation)입니다.",
    "실제로는 경기 간 상관관계가 있을 수 있어 실제 확률과 차이가 날 수 있습니다.",
    "조합 배당은 각 경기 시장 배당의 곱이며, 북메이커 마진이 누적되어 반영됩니다.",
]


class CombinationError(ValueError):
    """Invalid combination request (maps to HTTP 422)."""


def analyse_combination(
    session: Session, request: CombinationRequest, *, now: datetime, threshold: float
) -> CombinationOut:
    fixture_ids = [s.fixture_id for s in request.selections]
    if len(set(fixture_ids)) != len(fixture_ids):
        raise CombinationError("각 selection은 서로 다른 경기여야 합니다 (same-fixture 조합 불가).")

    seen_teams: set[int] = set()
    legs_out: list[CombinationLegOut] = []
    legs: list[Leg] = []
    for sel in request.selections:
        fixture = get_fixture(session, sel.fixture_id)
        if fixture is None:
            raise CombinationError(f"fixture {sel.fixture_id} not found")
        if fixture.status != FixtureStatus.SCHEDULED.value or fixture.kickoff_at <= now:
            raise CombinationError(f"fixture {sel.fixture_id} is not an upcoming match")
        teams = {fixture.home_team_id, fixture.away_team_id}
        if teams & seen_teams:
            raise CombinationError("같은 팀이 포함된 경기들은 상관관계 때문에 조합할 수 없습니다.")
        seen_teams |= teams

        prediction = latest_prediction(session, fixture.id)
        if prediction is None:
            raise CombinationError(f"fixture {sel.fixture_id} has no prediction yet")
        snapshot = prediction.odds_snapshot
        p_model = model_probabilities(prediction).get(sel.outcome)
        p_fair = market_view(snapshot).fair.get(sel.outcome)
        odds = odds_for(snapshot, sel.outcome)
        legs.append(Leg(p_model, p_fair, odds))
        legs_out.append(
            CombinationLegOut(
                fixture_id=fixture.id,
                home_team=TeamOut.model_validate(fixture.home_team),
                away_team=TeamOut.model_validate(fixture.away_team),
                kickoff_at=fixture.kickoff_at,
                outcome=sel.outcome,
                prediction_id=prediction.id,
                odds_snapshot_id=snapshot.id,
                odds_captured_at=snapshot.captured_at,
                decimal_odds=odds,
                model_probability=p_model,
                fair_probability=p_fair,
                edge=edge(p_model, p_fair),
                expected_value=expected_value(p_model, odds),
            )
        )

    res = combine(legs)
    return CombinationOut(
        legs=legs_out,
        model_probability=res.model_probability,
        fair_market_probability=res.fair_market_probability,
        combined_odds=res.combined_odds,
        implied_probability=res.implied_probability,
        edge=res.edge,
        expected_value=res.expected_value,
        exceeds_threshold=exceeds_threshold(res.edge, res.expected_value, threshold),
        value_threshold=threshold,
        method=METHOD,
        notes=APPROXIMATION_NOTES,
    )
