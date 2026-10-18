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
    logo_url: str | None = None


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


Region = Literal[
    "international",
    "europe",
    "asia",
    "south_america",
    "north_america",
    "africa",
    "oceania",
    "other",
]


class LeagueRefOut(ApiModel):
    id: int
    name: str
    country: str
    country_ko: str = Field(description="Country name for display (Korean when known)")
    region: Region
    type: Literal["league", "cup"]
    logo_url: str | None = None
    flag_url: str | None = None
    featured: bool = Field(description="Shown first (major leagues)")
    predicted: bool = Field(
        description="The model makes predictions here (league format with enough history)"
    )
    verified: bool = Field(
        description="Accuracy measured by a walk-forward backtest on real results"
    )


class LeagueSummaryOut(LeagueRefOut):
    current_season: str | None = None
    upcoming_count: int = Field(description="Fixtures in the requested window")
    predicted_count: int = Field(description="...of which the model has a prediction")


class CountryGroupOut(ApiModel):
    country: str
    country_ko: str
    flag_url: str | None = None
    leagues: list[LeagueSummaryOut]


class RegionGroupOut(ApiModel):
    region: Region
    region_ko: str
    countries: list[CountryGroupOut]


class LeagueListOut(ApiModel):
    data_provider: str
    days: int
    total_leagues: int
    featured: list[LeagueSummaryOut]
    regions: list[RegionGroupOut]


class FixtureSummaryOut(ApiModel):
    id: int
    league: LeagueRefOut
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
    prediction_odds: OddsSnapshotOut | None = Field(
        default=None,
        description="Odds snapshot the stored prediction uses (combinations are priced on it);"
        " can be older than latest_odds until the prediction is refreshed",
    )
    lineups_announced: bool = False


class FixtureListOut(ApiModel):
    date: str
    days: int
    tz: str
    data_provider: str = Field(description="Source of fixtures/odds, e.g. mock or api_football")
    bookmaker: str = Field(description="Bookmaker used as the market baseline")
    range_start_utc: datetime
    range_end_utc: datetime
    fixtures: list[FixtureSummaryOut]


class LineupPlayerOut(ApiModel):
    player_id: str
    name: str
    number: int | None = None
    position: str | None = None
    regular: bool = Field(description="Among the team's most used players in recent matches")


class AbsenceOut(ApiModel):
    player_id: str
    name: str
    status: Literal["out", "doubtful"]
    reason: str | None = None
    regular: bool


class MissingRegularOut(ApiModel):
    player_id: str
    name: str
    reason: str | None = Field(default=None, description="From the absence report, when known")


class TeamNewsSideOut(ApiModel):
    team_id: int
    team_name: str
    formation: str | None = None
    starters: list[LineupPlayerOut] = Field(default_factory=list)
    lineup_captured_at: datetime | None = None
    absences: list[AbsenceOut] = Field(default_factory=list)
    absences_captured_at: datetime | None = None
    missing_regulars: list[MissingRegularOut] = Field(
        default_factory=list,
        description="Regular starters not in the line-up (or reported out before it)",
    )
    regulars_known: bool = Field(
        description="Enough recent matches with player minutes to tell regulars apart"
    )
    recent_matches: int = Field(description="Matches used to find the regular starters")


class TeamNewsOut(ApiModel):
    lineups_announced: bool
    home: TeamNewsSideOut
    away: TeamNewsSideOut
    used_by_model: bool = Field(
        default=False, description="Whether model probabilities use this information"
    )
    note: str = (
        "선발 명단과 결장 정보는 참고용으로 보여 드립니다. 분석 확률에는 아직 반영하지 않았어요."
    )


class ScoreFrequencyOut(ApiModel):
    home: int
    away: int
    share: float = Field(description="Share of simulated matches with this score")
    exact: float = Field(description="Model probability of this score (score matrix)")


class GoalEventOut(ApiModel):
    minute: int
    side: Literal["home", "away"]


class ReplayOut(ApiModel):
    home_goals: int
    away_goals: int
    goals: list[GoalEventOut]


class SimulationOut(ApiModel):
    fixture_id: int
    prediction_id: int
    runs: int
    seed: int
    expected_goals: ExpectedGoalsOut
    outcome_share: ProbabilitiesOut = Field(description="Simulated home / draw / away shares")
    model_probabilities: ProbabilitiesOut = Field(description="The prediction being simulated")
    standard_error: float = Field(description="Largest sampling error (1 s.e.) of the shares")
    top_scores: list[ScoreFrequencyOut]
    total_goals: list[tuple[str, float]]
    over: dict[str, float]
    both_teams_score: float
    home_clean_sheet: float
    away_clean_sheet: float
    replay: ReplayOut
    note: str = (
        "시뮬레이션은 분석 확률(기대 득점)로 경기를 여러 번 다시 치러 본 결과입니다. "
        "새로운 정보를 더하지 않으므로 결과 비율은 분석 확률과 거의 같아야 정상이며, "
        "실제 결과를 보장하지 않습니다."
    )


class FixtureDetailOut(FixtureSummaryOut):
    odds_history: list[OddsSnapshotOut]
    team_news: TeamNewsOut | None = None


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
    quality: QualityOut | None = None
    disclaimer: str = DISCLAIMER


class SelectionIn(ApiModel):
    fixture_id: int
    outcome: Outcome
    # The prediction the user saw when choosing (its odds are the shown price). If a
    # newer prediction exists the request is refused (409) instead of being priced
    # on odds the user never saw.
    prediction_id: int


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


HighlightCaveat = Literal["promoted_home", "promoted_away", "large_gap", "unverified_league"]


class HighlightOut(ApiModel):
    fixture: FixtureSummaryOut
    outcome: Outcome
    model_probability: Probability
    fair_probability: Probability
    edge: float = Field(description="model_probability - fair_probability (> 0 by construction)")
    decimal_odds: float
    expected_value: float
    caveats: list[HighlightCaveat] = Field(
        description="Reasons the model may be unreliable for this match"
    )


class HighlightListOut(ApiModel):
    range_start_utc: datetime
    range_end_utc: datetime
    min_edge: float
    items: list[HighlightOut]
    note: str = (
        "추천이 아닙니다. 통계 분석과 시장(배당)의 생각이 가장 다른 경기를 모은 참고 정보입니다."
    )


# ---------------------------------------------------------------- data quality
class QualityCheckOut(ApiModel):
    name: str
    passed: bool
    detail: str


class QualityOut(ApiModel):
    ok: bool
    checks: list[QualityCheckOut]


class DataStatusOut(ApiModel):
    provider: str
    is_demo: bool
    bookmaker: str
    status: Literal["ok", "stale"]
    last_success_at: datetime | None
    last_success_age_hours: float | None
    ingest_max_age_hours: float
    recent_failures: int
    last_error: str | None
    latest_odds_captured_at: datetime | None
    latest_prediction_at: datetime | None


# ---------------------------------------------------------------- Today's Pick
PICK_DISCLAIMER = (
    "오늘의 픽은 선정 시각부터 다음 날 같은 시각까지의 경기 중 통계 모델이 가장 높은 가능성을 "
    "계산한 결과 하나를 설명합니다. "
    "확률은 추정치이며 결과를 보장하지 않고, 베팅 권유가 아닙니다."
)


class PickBacktestOut(ApiModel):
    dataset: str
    period: str | None
    threshold: float
    days_with_pick: int
    match_days: int
    hit_rate: float
    hit_rate_ci: list[float]
    mean_pick_probability: float
    leagues: list[str] = Field(default_factory=list, description="Leagues pooled in the replay")
    decision_hour: int | None = Field(
        default=None,
        description="Replay decided at this local hour like the service; null = whole-day replay",
    )


class PickCandidateOut(ApiModel):
    fixture_id: int
    league: str | None = None
    home: str
    away: str
    kickoff_at: datetime
    best_outcome: Outcome | None = None
    best_probability: float | None = None
    eligible: bool
    excluded_reasons: list[str]


class PickResultOut(ApiModel):
    event: Literal["settled", "voided"]
    actual_outcome: Outcome | None
    hit: bool | None
    reason: str | None
    recorded_at: datetime


TodayPickStatus = Literal[
    "scheduled", "published", "no_qualifying_match", "no_matches", "voided", "settled"
]


class TodayPickOut(ApiModel):
    date: str
    tz: str
    status: TodayPickStatus
    is_demo: bool
    publish_at: datetime
    window_start: datetime | None = Field(
        default=None, description="Candidates kick off in [window_start, window_end)"
    )
    window_end: datetime | None = None
    threshold: float
    pick_id: int | None = None
    revision: int | None = None
    published_at: datetime | None = None
    fixture: FixtureSummaryOut | None = None
    outcome: Outcome | None = None
    probability: Probability | None = None
    probabilities: ProbabilitiesOut | None = None
    expected_goals: ExpectedGoalsOut | None = None
    model: ModelVersionOut | None = None
    prediction_id: int | None = None
    input_data_as_of: datetime | None = None
    factors_used: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    quality_checks: list[QualityCheckOut] = Field(default_factory=list)
    candidates: list[PickCandidateOut] = Field(default_factory=list)
    league_scope: str = Field(
        default="verified", description="verified | all | explicit league ids"
    )
    matches_today: int | None = None
    matches_in_scope: int | None = Field(
        default=None, description="Matches of the pick window in leagues the pick may come from"
    )
    backtest: PickBacktestOut | None = None
    result: PickResultOut | None = None
    disclaimer: str = PICK_DISCLAIMER


class PickHistoryItemOut(ApiModel):
    pick_id: int
    date: str
    revision: int
    status: TodayPickStatus
    fixture_id: int | None
    home: str | None
    away: str | None
    kickoff_at: datetime | None
    outcome: Outcome | None
    probability: float | None
    model_version: str | None
    actual_outcome: Outcome | None
    hit: bool | None
    reason: str | None
    published_at: datetime
    recorded_before_kickoff: bool | None = Field(
        None, description="False: written after the match started, not counted in the summary"
    )


class PickHistorySummaryOut(ApiModel):
    published: int
    settled: int
    voided: int
    pending: int
    late_recorded: int = Field(
        0, description="Picks written after their match started, left out of every count above"
    )
    hits: int
    hit_rate: float | None
    hit_rate_ci: list[float] | None
    mean_probability: float | None


class PickHistoryOut(ApiModel):
    is_demo: bool
    items: list[PickHistoryItemOut]
    summary: PickHistorySummaryOut
    note: str = (
        "선정 당시의 확률을 그대로 보존합니다. 표본이 작을 때의 적중률은 우연의 영향이 큽니다."
    )


# ---------------------------------------------------------------- performance
class ModelMetricOut(ApiModel):
    name: str
    n: int
    log_loss: float
    log_loss_ci: list[float]
    brier: float
    rps: float
    accuracy: float
    ece: float


class SeasonMetricOut(ApiModel):
    season: str
    n: int
    log_loss: float
    brier: float
    accuracy: float


class CalibrationBinOut(ApiModel):
    outcome: Outcome
    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    observed_frequency: float | None


class DailyPickBacktestRowOut(ApiModel):
    min_probability: float
    decision_hour: int | None = Field(
        default=None, description="Local hour of the decision; null = every match of the day"
    )
    eligible_matches: int | None = None
    coverage: float | None = Field(default=None, description="Share of match days with a pick")
    match_days: int
    days_with_pick: int
    hits: int
    hit_rate: float | None
    hit_rate_ci: list[float] | None
    mean_pick_probability: float | None


class LeagueModelMetricOut(ApiModel):
    log_loss: float
    brier: float
    accuracy: float
    ece: float


class LeagueEvaluationOut(ApiModel):
    code: str
    name: str
    country: str
    test_matches: int
    production: LeagueModelMetricOut
    base_rate: LeagueModelMetricOut
    elo_only: LeagueModelMetricOut | None = None
    gain_vs_base_rate: list[float] = Field(
        description="[mean, ci_low, ci_high] log-loss improvement over the base rate"
    )
    verified: bool
    data_warnings: list[str] = Field(default_factory=list)


class MarketLeagueOut(ApiModel):
    code: str
    name: str
    n_matches: int
    production_log_loss: float
    market_log_loss: float
    production_accuracy: float
    market_accuracy: float


class ValueFlagOut(ApiModel):
    threshold: float
    flags: int
    hit_rate: float | None
    mean_return: float | None = Field(description="Average return per 1 unit at the market odds")
    mean_return_ci: list[float | None]


class MarketBaselineOut(ApiModel):
    """Production model vs the de-margined bookmaker market on past seasons."""

    dataset: str
    period: str
    n_matches: int
    production: LeagueModelMetricOut
    market: LeagueModelMetricOut
    log_loss_diff: float = Field(description="market - production (negative: market better)")
    log_loss_diff_ci: list[float]
    leagues: list[MarketLeagueOut] = Field(default_factory=list)
    value_flags: list[ValueFlagOut] = Field(
        default_factory=list,
        description="Outcomes the service flags as a large gap, and what they returned"
        " (descriptive; the service never bets)",
    )


class EvaluationOut(ApiModel):
    id: int
    created_at: datetime
    dataset: str
    license: str | None
    n_matches: int
    seasons: list[str]
    has_odds: bool
    split: dict[str, str]
    production_version: str
    validation: list[ModelMetricOut]
    test: list[ModelMetricOut]
    test_per_season: list[SeasonMetricOut]
    calibration: list[CalibrationBinOut]
    daily_picks: list[DailyPickBacktestRowOut]
    daily_picks_leagues: list[str] = Field(default_factory=list)
    daily_picks_timing: list[DailyPickBacktestRowOut] = Field(
        default_factory=list,
        description="Same rule replayed with the service's timing (decided at the publish hour,"
        " later kickoffs only). Timing only: not a replay of live odds or quality checks.",
    )
    leagues: list[LeagueEvaluationOut] = Field(default_factory=list)
    market_baseline: MarketBaselineOut | None = None
    promotion_decisions: dict[str, list[str]]


class LiveSideOut(ApiModel):
    log_loss: float
    log_loss_ci: list[float]
    brier: float


class LiveEvaluationOut(ApiModel):
    provider: str
    is_demo: bool
    n_matches: int
    model: LiveSideOut | None = None
    market: LiveSideOut | None = None


class PerformanceOut(ApiModel):
    evaluation: EvaluationOut | None
    live: LiveEvaluationOut
    note: str = (
        "백테스트는 과거 실제 경기 결과(openfootball)로 계산했습니다. "
        "공개 데이터에 과거 배당이 없어 시장 확률과의 과거 비교는 포함되지 않았고, "
        "실시간 비교는 수집된 예측이 쌓이면 표시됩니다."
    )


PredictionOut.model_rebuild()
