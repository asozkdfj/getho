/**
 * @edge/contracts - the API contract shared by web (and future clients).
 *
 * `generated/api.ts` is produced from apps/api's OpenAPI schema:
 *   make contracts   (python export -> openapi-typescript)
 * CI fails if the committed files drift from the API.
 */
import type { components } from "./generated/api";

type Schemas = components["schemas"];

export type HealthOut = Schemas["HealthOut"];
export type Team = Schemas["TeamOut"];
export type LeagueRef = Schemas["LeagueRefOut"];
export type LeagueSummary = Schemas["LeagueSummaryOut"];
export type LeagueList = Schemas["LeagueListOut"];
export type RegionGroup = Schemas["RegionGroupOut"];
export type CountryGroup = Schemas["CountryGroupOut"];
export type Region = LeagueRef["region"];
export type Probabilities = Schemas["ProbabilitiesOut"];
export type OddsSnapshot = Schemas["OddsSnapshotOut"];
export type FixtureSummary = Schemas["FixtureSummaryOut"];
export type FixtureList = Schemas["FixtureListOut"];
export type FixtureDetail = Schemas["FixtureDetailOut"];
export type ModelVersion = Schemas["ModelVersionOut"];
export type OutcomeAnalysis = Schemas["OutcomeAnalysisOut"];
export type Prediction = Schemas["PredictionOut"];
export type Selection = Schemas["SelectionIn"];
export type CombinationRequest = Schemas["CombinationRequest"];
export type CombinationLeg = Schemas["CombinationLegOut"];
export type Combination = Schemas["CombinationOut"];
export type Highlight = Schemas["HighlightOut"];
export type HighlightList = Schemas["HighlightListOut"];
export type HighlightCaveat = Highlight["caveats"][number];
export type Simulation = Schemas["SimulationOut"];
export type SimulationReplay = Schemas["ReplayOut"];
export type TeamNews = Schemas["TeamNewsOut"];
export type TeamNewsSide = Schemas["TeamNewsSideOut"];
export type LineupPlayer = Schemas["LineupPlayerOut"];
export type Absence = Schemas["AbsenceOut"];
export type Quality = Schemas["QualityOut"];
export type QualityCheck = Schemas["QualityCheckOut"];
export type DataStatus = Schemas["DataStatusOut"];
export type TodayPick = Schemas["TodayPickOut"];
export type TodayPickStatus = TodayPick["status"];
export type PickCandidate = Schemas["PickCandidateOut"];
export type PickHistory = Schemas["PickHistoryOut"];
export type PickHistoryItem = Schemas["PickHistoryItemOut"];
export type Performance = Schemas["PerformanceOut"];
export type Evaluation = Schemas["EvaluationOut"];
export type ModelMetric = Schemas["ModelMetricOut"];
export type CalibrationBin = Schemas["CalibrationBinOut"];
export type DailyPickBacktestRow = Schemas["DailyPickBacktestRowOut"];
export type MarketBaseline = Schemas["MarketBaselineOut"];
export type Review = Schemas["ReviewOut"];
export type ReviewItem = Schemas["ReviewItemOut"];
export type ReviewSummary = Schemas["ReviewSummaryOut"];
export type Research = Schemas["ResearchOut"];
export type ResearchDay = Schemas["ResearchDayOut"];
export type LiveClv = Schemas["LiveClvOut"];
export type ShadowProgress = Schemas["ShadowProgressOut"];
export type PersonalPickIn = Schemas["PersonalPickIn"];
export type PersonalPickRevisionIn = Schemas["PersonalPickRevisionIn"];
export type PersonalPick = Schemas["PersonalPickOut"];
export type PersonalPickDetail = Schemas["PersonalPickDetailOut"];
export type PersonalPickList = Schemas["PersonalPickListOut"];
export type PersonalPickRevision = Schemas["PersonalPickRevisionOut"];
export type PickAnalysis = Schemas["PickAnalysisOut"];
export type PickTeamNewsSide = Schemas["PickTeamNewsSideOut"];
export type PickSourceType = PersonalPickRevision["source_type"];

export type Outcome = Schemas["Outcome"];
export const OUTCOMES = ["HOME", "DRAW", "AWAY"] as const satisfies readonly Outcome[];

export const FIXTURE_STATUSES = [
  "scheduled",
  "live",
  "finished",
  "postponed",
  "cancelled",
] as const;
export type FixtureStatus = (typeof FIXTURE_STATUSES)[number];

export const MIN_COMBINATION_LEGS = 2;
export const MAX_COMBINATION_LEGS = 3;
