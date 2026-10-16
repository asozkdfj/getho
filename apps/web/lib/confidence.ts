import type { FixtureSummary, Outcome } from "@edge/contracts";

/**
 * How clear-cut a match is, from the model's most likely outcome. Thresholds and
 * the historical hit rates come from walk-forward predictions of the production
 * model on 9 verified leagues (2023-24..2025-26, docs/qa/2026-10-16-confidence-and-auto-combo.md);
 * the market's favourite hits these matches just as often, so a tier means
 * "a clear favourite", not "the model knows something the market does not".
 */
export const CONFIDENCE_HIGH = 0.65;
export const CONFIDENCE_MEDIUM = 0.55;

export type ConfidenceTier = "high" | "medium";

export const CONFIDENCE_TEXT: Record<ConfidenceTier, { label: string; detail: string }> = {
  high: {
    label: "확률 높음",
    detail:
      "가장 높은 결과의 분석 확률이 65% 이상이에요. 과거 3시즌 이런 경기의 실제 적중은 약 77%였어요.",
  },
  medium: {
    label: "확률 다소 높음",
    detail:
      "가장 높은 결과의 분석 확률이 55~65%예요. 과거 3시즌 이런 경기의 실제 적중은 약 61%였어요.",
  },
};

type Probabilities = NonNullable<FixtureSummary["model_probabilities"]>;

/** The most likely outcome (ties: HOME > AWAY > DRAW, like the pick rule). */
export function topOutcome(p: Probabilities): { outcome: Outcome; probability: number } {
  const order: [Outcome, number][] = [
    ["HOME", p.home],
    ["AWAY", p.away],
    ["DRAW", p.draw],
  ];
  const [outcome, probability] = order.reduce((best, cur) => (cur[1] > best[1] ? cur : best));
  return { outcome, probability };
}

export interface Confidence {
  tier: ConfidenceTier;
  outcome: Outcome;
  probability: number;
}

/**
 * Tier of an upcoming match in a verified league; null when not clear-cut or not
 * rated. On demo data (synthetic leagues, never verified) every predicted league
 * takes part, as for Today's Pick.
 */
export function confidence(f: FixtureSummary, demo = false): Confidence | null {
  if (f.status !== "scheduled" || !(f.league.verified || demo) || !f.model_probabilities) {
    return null;
  }
  const top = topOutcome(f.model_probabilities);
  if (top.probability >= CONFIDENCE_HIGH) return { tier: "high", ...top };
  if (top.probability >= CONFIDENCE_MEDIUM) return { tier: "medium", ...top };
  return null;
}
