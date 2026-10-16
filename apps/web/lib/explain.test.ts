import type { OutcomeAnalysis, Prediction } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import { UNVERIFIED_LEAGUE_CAUTION, plainSummary } from "./explain";

function row(outcome: "HOME" | "DRAW" | "AWAY", model: number, fair: number, odds: number) {
  const edge = model - fair;
  const ev = model * odds - 1;
  return {
    outcome,
    decimal_odds: odds,
    implied_probability: 1 / odds,
    fair_probability: fair,
    model_probability: model,
    edge,
    expected_value: ev,
    exceeds_threshold: edge >= 0.03 && ev >= 0.03,
  } satisfies OutcomeAnalysis;
}

function prediction(
  outcomes: OutcomeAnalysis[],
  features: Record<string, unknown> = {},
): Prediction {
  return { outcomes, features } as unknown as Prediction;
}

describe("plainSummary", () => {
  it("names the most likely outcome and the biggest model-market gap", () => {
    const s = plainSummary(
      prediction([
        row("HOME", 0.46, 0.4, 2.4),
        row("DRAW", 0.25, 0.27, 3.5),
        row("AWAY", 0.29, 0.33, 2.9),
      ]),
      "Brentford",
      "Liverpool",
    );
    expect(s.mostLikely).toBe("분석으로는 Brentford 승리(46%) 가능성이 가장 높습니다.");
    expect(s.comparison).toContain("Brentford 승리 가능성을 분석은 46%, 시장은 40%");
    expect(s.comparison).toContain("6%p 더 높게");
    expect(s.ev).toContain("Brentford 승리: 분석이 맞다면 장기 평균으로 +10.4% 유리한 가격");
    expect(s.ev).toContain("참고만");
  });

  it("says when the model is below the market", () => {
    const s = plainSummary(
      prediction([
        row("HOME", 0.34, 0.56, 1.7),
        row("DRAW", 0.29, 0.24, 4),
        row("AWAY", 0.37, 0.2, 4.8),
      ]),
      "Fulham",
      "Hull City",
    );
    expect(s.comparison).toContain("Fulham 승리 가능성을 분석은 34%, 시장은 56%");
    expect(s.comparison).toContain("22%p 더 낮게");
  });

  it("warns about promoted teams and very large gaps", () => {
    const s = plainSummary(
      prediction(
        [row("HOME", 0.34, 0.56, 1.7), row("DRAW", 0.29, 0.24, 4), row("AWAY", 0.37, 0.2, 4.8)],
        { prior_home: "data", prior_away: "promoted_relegation_level" },
      ),
      "Fulham",
      "Hull City",
    );
    expect(s.cautions).toEqual([
      "Hull City: 승격팀이라 이번 시즌 데이터가 적어 분석이 부정확할 수 있어요",
      "차이가 매우 커요. 시장은 부상·이적 같은 최신 소식을 이미 반영했을 수 있어요",
    ]);
  });

  it("reports agreement and no EV note when differences are small", () => {
    const s = plainSummary(
      prediction([
        row("HOME", 0.48, 0.47, 2),
        row("DRAW", 0.25, 0.26, 3.6),
        row("AWAY", 0.27, 0.27, 3.5),
      ]),
      "A",
      "B",
    );
    expect(s.comparison).toMatch(/거의 같습니다/);
    expect(s.ev).toBeNull();
    expect(s.cautions).toEqual([]);
  });

  it("adds a caution for leagues whose accuracy is not measured", () => {
    const rows = [
      row("HOME", 0.48, 0.47, 2),
      row("DRAW", 0.25, 0.26, 3.6),
      row("AWAY", 0.27, 0.27, 3.5),
    ];
    const s = plainSummary(prediction(rows), "A", "B", false);
    expect(s.cautions).toEqual([UNVERIFIED_LEAGUE_CAUTION]);
  });

  it("never uses guaranteeing or prescriptive words", () => {
    const s = plainSummary(
      prediction([
        row("HOME", 0.7, 0.5, 2.1),
        row("DRAW", 0.2, 0.3, 3.2),
        row("AWAY", 0.1, 0.2, 4.5),
      ]),
      "A",
      "B",
    );
    for (const text of [s.mostLikely, s.comparison, s.ev ?? ""]) {
      expect(text).not.toMatch(/확실|무조건|필승|보장|추천|베팅하세요/);
    }
  });
});
