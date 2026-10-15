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
