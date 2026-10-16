import type { FixtureSummary } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import { suggestCombination } from "./autoCombo";
import { TEST_LEAGUE } from "./testing";

const ODDS = {
  id: 1,
  bookmaker: "bet365",
  market: "1X2",
  odds_home: 2,
  odds_draw: 3.4,
  odds_away: 3.8,
  captured_at: "2026-10-15T06:30:00Z",
};

function fx(
  id: number,
  home: number,
  away: number,
  top: number,
  extra: Partial<FixtureSummary> = {},
): FixtureSummary {
  const rest = (1 - top) / 2;
  return {
    id,
    league: TEST_LEAGUE,
    season: "2026-27",
    round: 1,
    kickoff_at: `2026-10-16T1${id % 10}:00:00Z`,
    status: "scheduled",
    home_team: { id: home, name: `T${home}`, short_name: `T${home}` },
    away_team: { id: away, name: `T${away}`, short_name: `T${away}` },
    home_score: null,
    away_score: null,
    lineups_announced: false,
    latest_odds: ODDS,
    fair_market_probabilities: { home: 0.45, draw: 0.28, away: 0.27 },
    model_probabilities: { home: top, draw: rest, away: rest },
    prediction_id: id * 100,
    prediction_odds: ODDS,
    ...extra,
  } as FixtureSummary;
}

describe("auto combination", () => {
  it("takes the most likely outcomes and multiplies their probabilities", () => {
    const all = [fx(1, 1, 2, 0.5), fx(2, 3, 4, 0.8), fx(3, 5, 6, 0.7), fx(4, 7, 8, 0.6)];
    const s = suggestCombination(all, 2)!;
    expect(s.legs.map((l) => l.fixture.id)).toEqual([2, 3]);
    expect(s.selections).toEqual({ 2: "HOME", 3: "HOME" });
    expect(s.probability).toBeCloseTo(0.56);
    expect(suggestCombination(all, 3)!.legs.map((l) => l.fixture.id)).toEqual([2, 3, 4]);
  });

  it("picks the away side or the draw when that is the most likely outcome", () => {
    const away = fx(1, 1, 2, 0.7, { model_probabilities: { home: 0.1, draw: 0.2, away: 0.7 } });
    const s = suggestCombination([away, fx(2, 3, 4, 0.6)], 2)!;
    expect(s.selections[1]).toBe("AWAY");
  });

  it("never uses a team twice and searches for the best valid set", () => {
    // 1 and 2 share team 1: the best pair is 1 + 3, not 1 + 2
    const all = [fx(1, 1, 2, 0.9), fx(2, 1, 3, 0.85), fx(3, 4, 5, 0.6)];
    const s = suggestCombination(all, 2)!;
    expect(s.legs.map((l) => l.fixture.id)).toEqual([1, 3]);
  });

  it("only uses selectable matches of verified leagues", () => {
    const unverified = fx(1, 1, 2, 0.95, { league: { ...TEST_LEAGUE, verified: false } });
    const noOdds = fx(2, 3, 4, 0.9, { prediction_odds: null });
    const started = fx(3, 5, 6, 0.9, { status: "live" });
    const ok = [fx(4, 7, 8, 0.6), fx(5, 9, 10, 0.55)];
    const s = suggestCombination([unverified, noOdds, started, ...ok], 2)!;
    expect(s.legs.map((l) => l.fixture.id)).toEqual([4, 5]);
    expect(suggestCombination([unverified, ...ok], 3)).toBeNull(); // not enough matches
    // demo data: every league takes part
    expect(suggestCombination([unverified, ...ok], 3, true)!.legs[0]!.fixture.id).toBe(1);
  });

  it("is deterministic on ties (earlier kickoff first)", () => {
    const all = [fx(3, 1, 2, 0.7), fx(1, 3, 4, 0.7), fx(2, 5, 6, 0.7)];
    expect(suggestCombination(all, 2)!.legs.map((l) => l.fixture.id)).toEqual([1, 2]);
  });
});
