import { OUTCOMES, type Outcome, type Prediction } from "@edge/contracts";

import { pct, signedPct } from "./format";

/** Below this gap (2%p) the model and the market are treated as agreeing. */
export const AGREEMENT_BAND = 0.02;

export interface PlainSummary {
  mostLikely: string;
  comparison: string;
  ev: string | null;
}

function outcomeText(outcome: Outcome, home: string, away: string): string {
  if (outcome === "HOME") return `${home} 승리`;
  if (outcome === "AWAY") return `${away} 승리`;
  return "무승부";
}

/**
 * Beginner-friendly sentences for one prediction. Wording is deliberately
 * descriptive ("모델은 ~로 봅니다"), never prescriptive or guaranteeing.
 */
export function plainSummary(p: Prediction, home: string, away: string): PlainSummary {
  const rows = OUTCOMES.map((o) => p.outcomes.find((r) => r.outcome === o)!);
  const likely = rows.reduce((a, b) => (b.model_probability > a.model_probability ? b : a));
  const gap = rows.reduce((a, b) => (Math.abs(b.edge) > Math.abs(a.edge) ? b : a));

  const mostLikely =
    `모델이 가장 가능성이 높다고 보는 결과는 ${outcomeText(likely.outcome, home, away)}` +
    `(${pct(likely.model_probability, 0)})입니다.`;

  const comparison =
    Math.abs(gap.edge) < AGREEMENT_BAND
      ? "모델과 시장(배당)의 시각이 거의 같습니다. 세 결과 모두 차이가 2%p 미만입니다."
      : `${outcomeText(gap.outcome, home, away)} 가능성을 모델은 ${pct(gap.model_probability, 0)}, ` +
        `시장은 ${pct(gap.fair_probability, 0)}로 봐서, 모델이 ` +
        `${Math.abs(gap.edge * 100).toFixed(0)}%p 더 ${gap.edge > 0 ? "높게" : "낮게"} 봅니다.`;

  const flagged = rows.filter((r) => r.exceeds_threshold);
  const ev =
    flagged.length === 0
      ? null
      : flagged
          .map(
            (r) =>
              `${outcomeText(r.outcome, home, away)}: 모델이 맞다면 장기 평균 기대값 ` +
              `${signedPct(r.expected_value)}`,
          )
          .join(" · ") + " (모델 오차가 클 수 있어 참고용입니다)";

  return { mostLikely, comparison, ev };
}
