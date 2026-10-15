import type { Highlight } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import { caveatText, highlightSentence, outcomeName } from "./highlights";
import { TEST_LEAGUE } from "./testing";

const base = {
  fixture: {
    id: 1,
    league: TEST_LEAGUE,
    season: "2026-27",
    round: 8,
    kickoff_at: "2026-10-17T14:00:00Z",
    status: "scheduled",
    home_team: { id: 1, name: "Fulham", short_name: "FUL" },
    away_team: { id: 2, name: "Hull City", short_name: "HUL" },
    home_score: null,
    away_score: null,
    lineups_announced: false,
  },
  outcome: "AWAY",
  model_probability: 0.31,
  fair_probability: 0.2,
  edge: 0.11,
  decimal_odds: 4.8,
  expected_value: 0.488,
  caveats: ["promoted_away", "large_gap"],
} satisfies Highlight;

describe("highlight wording", () => {
  it("describes the gap in plain words", () => {
    expect(outcomeName(base)).toBe("Hull City 승리");
    expect(highlightSentence(base)).toBe(
      "Hull City 승리 가능성을 분석은 31%, 시장은 20%로 봐요. 분석이 11%p 더 높게 봅니다.",
    );
  });

  it("explains every caveat", () => {
    expect(caveatText("promoted_away", base)).toMatch(/^Hull City: 승격팀/);
    expect(caveatText("promoted_home", base)).toMatch(/^Fulham: 승격팀/);
    expect(caveatText("large_gap", base)).toMatch(/최신 소식/);
    expect(caveatText("unverified_league", base)).toMatch(/검증하지 않았어요/);
  });

  it("never sounds like a tip", () => {
    const all = [highlightSentence(base), ...base.caveats.map((c) => caveatText(c, base))];
    for (const t of all) expect(t).not.toMatch(/추천|확실|무조건|필승|보장|베팅하세요/);
  });
});
