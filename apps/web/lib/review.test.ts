import type { ReviewSummary } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import { luckNote, marketText, resultTag, reviewSummaryText, shiftDate, topLabel } from "./review";

const summary = (matches: number, hits: number, expected: number): ReviewSummary => ({
  matches,
  hits,
  expected_hits: expected,
  hit_variance: matches * 0.25,
  market_hits: hits,
  market_expected_hits: expected,
  tiers: {},
});

describe("review texts", () => {
  it("compares hits with the expected number", () => {
    expect(reviewSummaryText(summary(0, 0, 0))).toMatch(/결과가 나온 분석 경기가 없어요/);
    expect(reviewSummaryText(summary(10, 4, 5.3))).toMatch(/10개 중 4개.*약 5\.3개/);
    expect(marketText(summary(10, 6, 5.5))).toMatch(/1순위는 6개.*5\.5개/);
  });

  it("calls a small gap normal and a large one unusual", () => {
    expect(luckNote(summary(10, 4, 5))).toMatch(/흔히 나오는 범위/);
    expect(luckNote(summary(10, 0, 5))).toMatch(/꽤 적게/);
    expect(luckNote(summary(10, 10, 5))).toMatch(/꽤 많이/);
    expect(luckNote(summary(0, 0, 0))).toBe("");
  });

  it("labels outcomes, results and dates", () => {
    expect(topLabel({ top_outcome: "AWAY", top_probability: 0.62 })).toBe("원정승 62%");
    expect(topLabel({ top_outcome: null, top_probability: null })).toBe("분석 없음");
    expect(resultTag({ hit: true, status: "finished" }).text).toBe("적중");
    expect(resultTag({ hit: false, status: "finished" }).tone).toBe("negative");
    expect(resultTag({ hit: null, status: "postponed" }).text).toBe("연기·취소");
    expect(resultTag({ hit: null, status: "scheduled" }).text).toBe("결과 전");
    expect(shiftDate("2026-10-17", -1)).toBe("2026-10-16");
    expect(shiftDate("2026-10-31", 1)).toBe("2026-11-01");
  });
});
