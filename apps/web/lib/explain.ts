import { OUTCOMES, type Outcome, type Prediction } from "@edge/contracts";

import { pct, signedPct } from "./format";

/** Below this gap (2%p) the model and the market are treated as agreeing. */
export const AGREEMENT_BAND = 0.02;

export interface PlainSummary {
  mostLikely: string;
  comparison: string;
  ev: string | null;
  /** reasons the analysis may be unreliable for this match */
  cautions: string[];
}

/** A gap this large usually means the market knows something the model doesn't. */
export const LARGE_GAP = 0.1;
const NEWCOMER_PRIORS = new Set(["promoted_relegation_level", "unseen_relegation_level"]);

export const promotedCaution = (team: string) =>
  `${team}: 승격팀이라 이번 시즌 데이터가 적어 분석이 부정확할 수 있어요`;
export const UNVERIFIED_LEAGUE_CAUTION =
  "이 리그는 과거 기록으로 분석의 정확도를 아직 검증하지 않았어요";
export const LARGE_GAP_CAUTION =
  "차이가 매우 커요. 시장은 부상·이적 같은 최신 소식을 이미 반영했을 수 있어요";

function outcomeText(outcome: Outcome, home: string, away: string): string {
  if (outcome === "HOME") return `${home} 승리`;
  if (outcome === "AWAY") return `${away} 승리`;
  return "무승부";
}

/**
 * Beginner-friendly sentences for one prediction. Wording is deliberately
 * descriptive ("모델은 ~로 봅니다"), never prescriptive or guaranteeing.
 */
export function plainSummary(
  p: Prediction,
  home: string,
  away: string,
  verifiedLeague = true,
): PlainSummary {
  const rows = OUTCOMES.map((o) => p.outcomes.find((r) => r.outcome === o)!);
  const likely = rows.reduce((a, b) => (b.model_probability > a.model_probability ? b : a));
  const gap = rows.reduce((a, b) => (Math.abs(b.edge) > Math.abs(a.edge) ? b : a));

  const mostLikely =
    `분석으로는 ${outcomeText(likely.outcome, home, away)}` +
    `(${pct(likely.model_probability, 0)}) 가능성이 가장 높습니다.`;

  const comparison =
    Math.abs(gap.edge) < AGREEMENT_BAND
      ? "분석과 시장(배당)의 생각이 거의 같습니다. 세 결과 모두 차이가 2%p보다 작아요."
      : `${outcomeText(gap.outcome, home, away)} 가능성을 분석은 ${pct(gap.model_probability, 0)}, ` +
        `시장은 ${pct(gap.fair_probability, 0)}로 봐요. 분석이 ` +
        `${Math.abs(gap.edge * 100).toFixed(0)}%p 더 ${gap.edge > 0 ? "높게" : "낮게"} 봅니다.`;

  const flagged = rows.filter((r) => r.exceeds_threshold);
  const ev =
    flagged.length === 0
      ? null
      : flagged
          .map(
            (r) =>
              `${outcomeText(r.outcome, home, away)}: 분석이 맞다면 장기 평균으로 ` +
              `${signedPct(r.expected_value)} 유리한 가격`,
          )
          .join(" · ") + " (분석이 틀릴 수 있어 참고만 하세요)";

  const cautions: string[] = [];
  const features = (p.features ?? {}) as Record<string, unknown>;
  for (const [key, team] of [
    ["prior_home", home],
    ["prior_away", away],
  ] as const) {
    if (NEWCOMER_PRIORS.has(String(features[key]))) {
      cautions.push(promotedCaution(team));
    }
  }
  if (Math.abs(gap.edge) >= LARGE_GAP) {
    cautions.push(LARGE_GAP_CAUTION);
  }
  if (!verifiedLeague) {
    cautions.push(UNVERIFIED_LEAGUE_CAUTION);
  }

  return { mostLikely, comparison, ev, cautions };
}
