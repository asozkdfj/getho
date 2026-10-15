"""Public API contract (exported to packages/contracts/openapi.json)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from edge_ml.core import Outcome

DISCLAIMER = (
    "모델 확률은 통계적 추정치이며 경기 결과를 보장하지 않습니다. "
    "EPL Edge Lab은 데이터 분석 서비스로, 베팅을 중개하거나 실행하지 않습니다."
)

Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthOut(ApiModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]
    app_env: str
    git_sha: str


class TeamOut(ApiModel):
    id: int
    name: str
    short_name: str


class ProbabilitiesOut(ApiModel):
    home: Probability
    draw: Probability
    away: Probability


class OddsSnapshotOut(ApiModel):
    id: int
    bookmaker: str
    market: str
    odds_home: float
    odds_draw: float
    odds_away: float
    captured_at: datetime


class FixtureSummaryOut(ApiModel):
    id: int
    league: str
    season: str
    round: int | None
    kickoff_at: datetime
    status: str
    home_team: TeamOut
    away_team: TeamOut
    home_score: int | None
    away_score: int | None
    latest_odds: OddsSnapshotOut | None = None
    fair_market_probabilities: ProbabilitiesOut | None = None
    model_probabilities: ProbabilitiesOut | None = None
    prediction_id: int | None = None


class FixtureListOut(ApiModel):
    date: str
    days: int
    tz: str
    data_provider: str = Field(description="Source of fixtures/odds, e.g. mock or api_football")
    bookmaker: str = Field(description="Bookmaker used as the market baseline")
    range_start_utc: datetime
    range_end_utc: datetime
    fixtures: list[FixtureSummaryOut]


class FixtureDetailOut(FixtureSummaryOut):
    odds_history: list[OddsSnapshotOut]


class ModelVersionOut(ApiModel):
    id: int
    name: str
    version: str
    git_sha: str
    feature_set: str
    calibration: str


class OutcomeAnalysisOut(ApiModel):
    outcome: Outcome
    decimal_odds: float
    implied_probability: float = Field(description="1/odds, includes bookmaker margin")
    fair_probability: Probability = Field(description="de-vigged market probability")
    model_probability: Probability
    edge: float = Field(description="model_probability - fair_probability")
    expected_value: float = Field(description="model_probability * decimal_odds - 1")
    exceeds_threshold: bool = Field(
        description="edge AND EV >= value_threshold. A reference signal, not advice."
    )


class ExpectedGoalsOut(ApiModel):
    home: float
    away: float


class PredictionOut(ApiModel):
    prediction_id: int
    fixture_id: int
    created_at: datetime
    input_data_as_of: datetime
    model: ModelVersionOut
    market_odds_snapshot: OddsSnapshotOut
    probabilities: ProbabilitiesOut
    fair_market_probabilities: ProbabilitiesOut
    overround: float
    devig_method: str
    expected_goals: ExpectedGoalsOut
    outcomes: list[OutcomeAnalysisOut]
    value_threshold: float
    features: dict[str, Any]
    disclaimer: str = DISCLAIMER


class SelectionIn(ApiModel):
    fixture_id: int
    outcome: Outcome


class CombinationRequest(ApiModel):
    selections: list[SelectionIn] = Field(min_length=2, max_length=3)


class CombinationLegOut(ApiModel):
    fixture_id: int
    home_team: TeamOut
    away_team: TeamOut
    kickoff_at: datetime
    outcome: Outcome
    prediction_id: int
    odds_snapshot_id: int
    odds_captured_at: datetime
    decimal_odds: float
    model_probability: Probability
    fair_probability: Probability
    edge: float
    expected_value: float


class CombinationOut(ApiModel):
    legs: list[CombinationLegOut]
    model_probability: Probability
    fair_market_probability: Probability
    combined_odds: float
    implied_probability: float
    edge: float
    expected_value: float
    exceeds_threshold: bool
    value_threshold: float
    method: Literal["independence_approximation"]
    is_approximation: Literal[True] = True
    notes: list[str]
    disclaimer: str = DISCLAIMER


class ErrorOut(ApiModel):
    detail: str
