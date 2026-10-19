import type { FixtureSummary } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import { TEST_LEAGUE } from "./testing";
import { topWindowCombos } from "./windowCombos";

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
  hoursFromStart: number,
  top: number,
  teams?: [number, number],
  market: { home: number; draw: number; away: number } = { home: 0.5, draw: 0.25, away: 0.25 },
) {
  const rest = (1 - top) / 2;
  const [home, away] = teams ?? [id * 2, id * 2 + 1];
  return {
    id,
    league: TEST_LEAGUE,
    season: "2026-27",
    round: 1,
    kickoff_at: new Date(Date.UTC(2026, 9, 16, 10) + hoursFromStart * 3_600_000).toISOString(),
    status: "scheduled",
    home_team: { id: home, name: `T${home}`, short_name: `T${home}` },
    away_team: { id: away, name: `T${away}`, short_name: `T${away}` },
    home_score: null,
    away_score: null,
    lineups_announced: false,
    latest_odds: ODDS,
    fair_market_probabilities: market,
    model_probabilities: { home: top, draw: rest, away: rest },
    prediction_id: id * 100,
    prediction_odds: ODDS,
  } as FixtureSummary;
}

describe("topWindowCombos", () => {
  it("only combines matches whose kickoffs fit in the window", () => {
    // the two strongest matches are 10 hours apart and can never share a combination
    const fixtures = [fx(1, 0, 0.8), fx(2, 1, 0.5), fx(3, 2, 0.5), fx(4, 10, 0.8), fx(5, 11, 0.5)];
    const combos = topWindowCombos(fixtures, { windowHours: 8 });
    expect(combos.length).toBeGreaterThan(0);
    for (const c of combos) {
      expect(c.spanHours).toBeLessThanOrEqual(8);
      const ids = c.legs.map((l) => l.fixture.id);
      expect(ids.includes(1) && ids.includes(4)).toBe(false);
    }
    expect(combos[0]!.legs.map((l) => l.fixture.id)).toEqual([1, 2, 3]);
    expect(combos[0]!.probability).toBeCloseTo(0.8 * 0.5 * 0.5);
    expect(combos[0]!.marketProbability).toBeCloseTo(0.5 ** 3);
  });

  it("ranks by probability, returns at most five and never repeats a team", () => {
    const fixtures = Array.from({ length: 8 }, (_, i) => fx(i + 1, i * 0.5, 0.4 + i * 0.05));
    fixtures.push(fx(20, 1, 0.95, [16, 99])); // shares team 16 with fixture 8
    const combos = topWindowCombos(fixtures);
    expect(combos).toHaveLength(5);
    const probs = combos.map((c) => c.probability);
    expect([...probs].sort((a, b) => b - a)).toEqual(probs);
    for (const c of combos) {
      const teams = c.legs.flatMap((l) => [l.fixture.home_team.id, l.fixture.away_team.id]);
      expect(new Set(teams).size).toBe(teams.length);
    }
    expect(new Set(combos.map((c) => Object.keys(c.selections).join())).size).toBe(5);
  });

  it("is empty when fewer than three matches fit together", () => {
    expect(topWindowCombos([fx(1, 0, 0.7), fx(2, 9, 0.7), fx(3, 20, 0.7)])).toEqual([]);
  });

  it("can rank and pick outcomes by the market or the average", () => {
    const away = { home: 0.2, draw: 0.2, away: 0.6 };
    const fixtures = [
      fx(1, 0, 0.7), // model's favourite home win; market 50%
      fx(2, 1, 0.45, undefined, away), // market sees an away win at 60%
      fx(3, 2, 0.6),
      fx(4, 3, 0.55),
    ];
    const byModel = topWindowCombos(fixtures, { basis: "model" })[0]!;
    expect(byModel.legs.map((l) => l.fixture.id)).toEqual([1, 3, 4]);
    expect(byModel.score).toBeCloseTo(byModel.probability);
    const byMarket = topWindowCombos(fixtures, { basis: "market" })[0]!;
    const leg2 = byMarket.legs.find((l) => l.fixture.id === 2)!;
    expect(leg2.outcome).toBe("AWAY");
    expect(leg2.score).toBeCloseTo(0.6);
    expect(byMarket.score).toBeCloseTo(byMarket.marketProbability!);
    const avg = topWindowCombos(fixtures, { basis: "average" })[0]!;
    for (const l of avg.legs) expect(l.score).toBeCloseTo((l.probability + l.market!) / 2);
  });

  it("limits how often one match appears across the list", () => {
    const fixtures = Array.from({ length: 9 }, (_, i) => fx(i + 1, i * 0.5, i === 0 ? 0.9 : 0.5));
    const count = (combos: ReturnType<typeof topWindowCombos>) => {
      const seen = new Map<number, number>();
      combos.forEach((c) =>
        c.legs.forEach((l) => seen.set(l.fixture.id, (seen.get(l.fixture.id) ?? 0) + 1)),
      );
      return Math.max(...seen.values());
    };
    expect(count(topWindowCombos(fixtures, { overlap: "any" }))).toBe(5); // the 90% match everywhere
    expect(count(topWindowCombos(fixtures, { overlap: "max2" }))).toBeLessThanOrEqual(2);
    const none = topWindowCombos(fixtures, { overlap: "none" });
    expect(count(none)).toBe(1);
    expect(none).toHaveLength(3); // 9 matches make 3 disjoint combinations
  });

  it("widens with the window", () => {
    const fixtures = [fx(1, 0, 0.7), fx(2, 3, 0.7), fx(3, 6, 0.7)];
    expect(topWindowCombos(fixtures, { windowHours: 4 })).toEqual([]);
    expect(topWindowCombos(fixtures, { windowHours: 8 })).toHaveLength(1);
  });
});
