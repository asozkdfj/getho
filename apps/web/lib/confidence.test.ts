import type { FixtureSummary } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import { CONFIDENCE_TEXT, confidence, topOutcome } from "./confidence";
import { TEST_LEAGUE } from "./testing";

function fx(probs: FixtureSummary["model_probabilities"], extra: Partial<FixtureSummary> = {}) {
  return {
    id: 1,
    league: TEST_LEAGUE,
    season: "2026-27",
    round: 1,
    kickoff_at: "2026-10-16T12:30:00Z",
    status: "scheduled",
    home_team: { id: 1, name: "A", short_name: "A" },
    away_team: { id: 2, name: "B", short_name: "B" },
    home_score: null,
    away_score: null,
    lineups_announced: false,
    model_probabilities: probs,
    ...extra,
  } as FixtureSummary;
}

describe("confidence tiers", () => {
  it("uses the most likely outcome against the 65% / 55% thresholds", () => {
    expect(confidence(fx({ home: 0.7, draw: 0.18, away: 0.12 }))).toEqual({
      tier: "high",
      outcome: "HOME",
      probability: 0.7,
    });
    expect(confidence(fx({ home: 0.65, draw: 0.2, away: 0.15 }))?.tier).toBe("high");
    expect(confidence(fx({ home: 0.2, draw: 0.22, away: 0.58 }))).toMatchObject({
      tier: "medium",
      outcome: "AWAY",
    });
    expect(confidence(fx({ home: 0.549, draw: 0.25, away: 0.201 }))).toBeNull();
  });

  it("only rates upcoming matches of verified leagues with a model probability", () => {
    const strong = { home: 0.8, draw: 0.12, away: 0.08 };
    expect(confidence(fx(strong, { status: "finished" }))).toBeNull();
    expect(confidence(fx(strong, { league: { ...TEST_LEAGUE, verified: false } }))).toBeNull();
    expect(confidence(fx(null))).toBeNull();
    // demo data: synthetic leagues are never verified, so every league is rated
    const demo = fx(strong, { league: { ...TEST_LEAGUE, verified: false } });
    expect(confidence(demo, true)?.tier).toBe("high");
  });

  it("breaks ties like the pick rule and explains each tier", () => {
    expect(topOutcome({ home: 0.4, draw: 0.2, away: 0.4 }).outcome).toBe("HOME");
    expect(topOutcome({ home: 0.3, draw: 0.35, away: 0.35 }).outcome).toBe("AWAY");
    expect(CONFIDENCE_TEXT.high.detail).toMatch(/65% 이상.*77%/);
    expect(CONFIDENCE_TEXT.medium.detail).toMatch(/55~65%.*61%/);
  });
});
