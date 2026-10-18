import type { ReviewItem, ReviewSummary } from "@edge/contracts";

import { OUTCOME_SHORT, pct } from "./format";

/** One-line result of the day: hits against the number the probabilities expected. */
export function reviewSummaryText(s: ReviewSummary): string {
  if (s.matches === 0) return "이 날 결과가 나온 분석 경기가 없어요.";
  return (
    `분석이 가장 높게 본 결과 ${s.matches}개 중 ${s.hits}개가 맞았어요. ` +
    `확률대로라면 약 ${s.expected_hits.toFixed(1)}개가 맞을 날이었어요.`
  );
}

/**
 * Was the day unusual? Compares hits with the expected number, scaled by the
 * spread of the same matches (the summary's sum of p(1 - p)), so matches
 * outside the summary never change the verdict.
 */
export function luckNote(s: ReviewSummary): string {
  if (s.matches === 0) return "";
  const sd = Math.sqrt(s.hit_variance);
  const gap = s.hits - s.expected_hits;
  if (Math.abs(gap) <= Math.max(1, 1.5 * sd)) {
    return "확률로 보면 흔히 나오는 범위예요. 하루 결과로 모델이 맞다 틀리다를 판단하기는 어려워요.";
  }
  return gap < 0
    ? "기대보다 꽤 적게 맞았어요. 하루치라 운의 영향이 크지만, 이런 날이 이어지면 모델을 점검해야 해요."
    : "기대보다 꽤 많이 맞았어요. 이것도 운의 영향이 커서 다음 날 그대로 이어진다고 보긴 어려워요.";
}

export function marketText(s: ReviewSummary): string {
  if (s.matches === 0) return "";
  return `같은 경기에서 시장(배당)의 1순위는 ${s.market_hits}개 맞았어요 (기대 약 ${s.market_expected_hits.toFixed(1)}개).`;
}

/** e.g. "홈승 64%" for the model's most likely outcome. */
export function topLabel(i: Pick<ReviewItem, "top_outcome" | "top_probability">): string {
  if (!i.top_outcome || i.top_probability === null) return "분석 없음";
  return `${OUTCOME_SHORT[i.top_outcome]} ${pct(i.top_probability, 0)}`;
}

export function resultTag(i: Pick<ReviewItem, "hit" | "status">): { text: string; tone: string } {
  if (i.hit === true) return { text: "적중", tone: "positive" };
  if (i.hit === false) return { text: "빗나감", tone: "negative" };
  if (i.status === "postponed" || i.status === "cancelled")
    return { text: "연기·취소", tone: "muted" };
  return { text: "결과 전", tone: "muted" };
}

/** The previous / next local date (YYYY-MM-DD). */
export function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
