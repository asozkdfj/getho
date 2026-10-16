import type { FixtureSummary } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import {
  blockReason,
  isSelectable,
  legLabel,
  matchesTeam,
  selectedLegs,
  selectedPerLeague,
  toRequest,
  toggleSelection,
} from "./combination";
import { TEST_LEAGUE } from "./testing";

function fx(id: number, home: number, away: number, extra: Partial<FixtureSummary> = {}) {
  return {
    id,
    league: TEST_LEAGUE,
    season: "2026-27",
    round: 1,
    kickoff_at: "2026-10-16T12:30:00Z",
    status: "scheduled",
    home_team: { id: home, name: `T${home}`, short_name: `T${home}` },
    away_team: { id: away, name: `T${away}`, short_name: `T${away}` },
    home_score: null,
    away_score: null,
    lineups_announced: false,
    latest_odds: {
      id: id * 10,
      bookmaker: "mockbook",
      market: "1X2",
      odds_home: 2,
      odds_draw: 3.4,
      odds_away: 3.8,
      captured_at: "2026-10-15T06:30:00Z",
    },
    fair_market_probabilities: { home: 0.48, draw: 0.28, away: 0.24 },
    model_probabilities: { home: 0.5, draw: 0.27, away: 0.23 },
    prediction_id: id * 100,
    ...extra,
  } satisfies FixtureSummary;
}

const all = [fx(1, 1, 2), fx(2, 3, 4), fx(3, 5, 6), fx(4, 7, 8), fx(5, 1, 9)];

describe("combination selection", () => {
  it("adds, switches and removes selections", () => {
    let s = toggleSelection({}, all[0]!, "HOME", all);
    expect(s).toEqual({ 1: "HOME" });
    s = toggleSelection(s, all[0]!, "DRAW", all);
    expect(s).toEqual({ 1: "DRAW" });
    s = toggleSelection(s, all[0]!, "DRAW", all);
    expect(s).toEqual({});
  });

  it("limits to three legs", () => {
    let s = {};
    for (const f of all.slice(0, 4)) s = toggleSelection(s, f, "HOME", all);
    expect(Object.keys(s)).toHaveLength(3);
    expect(blockReason(s, all[3]!, all)).toMatch(/최대 3경기/);
  });

  it("blocks fixtures that share a team with a selected fixture", () => {
    const s = toggleSelection({}, all[0]!, "HOME", all);
    expect(blockReason(s, all[4]!, all)).toMatch(/같은 팀/);
    expect(toggleSelection(s, all[4]!, "AWAY", all)).toBe(s);
  });

  it("only allows upcoming fixtures with prediction and odds", () => {
    expect(isSelectable(fx(9, 10, 11, { status: "finished" }))).toBe(false);
    expect(isSelectable(fx(9, 10, 11, { prediction_id: null }))).toBe(false);
    expect(isSelectable(fx(9, 10, 11, { latest_odds: null }))).toBe(false);
    expect(blockReason({}, fx(9, 10, 11, { prediction_id: null }), all)).toMatch(/예측/);
  });

  it("builds the API request body", () => {
    expect(toRequest({ 1: "HOME", 2: "AWAY" })).toEqual({
      selections: [
        { fixture_id: 1, outcome: "HOME" },
        { fixture_id: 2, outcome: "AWAY" },
      ],
    });
  });
});

describe("picker helpers", () => {
  const named = [
    fx(1, 1, 2, {
      home_team: { id: 1, name: "Arsenal", short_name: "ARS" },
      away_team: { id: 2, name: "Crystal Palace", short_name: "CRY" },
    }),
    fx(2, 3, 4, {
      league: { ...TEST_LEAGUE, id: 2, name: "La Liga" },
      kickoff_at: "2026-10-17T19:00:00Z",
    }),
    fx(3, 5, 6, { league: { ...TEST_LEAGUE, id: 2, name: "La Liga" } }),
  ];

  it("searches team names on either side", () => {
    expect(matchesTeam(named[0]!, "palace")).toBe(true);
    expect(matchesTeam(named[0]!, " ars ")).toBe(true);
    expect(matchesTeam(named[0]!, "chelsea")).toBe(false);
    expect(matchesTeam(named[0]!, "")).toBe(true);
  });

  it("lists selections in list order with short labels", () => {
    const legs = selectedLegs({ 3: "DRAW", 1: "AWAY", 99: "HOME" }, named);
    expect(legs.map((l) => l.fixture.id)).toEqual([1, 3]);
    expect(legLabel(named[0]!, "AWAY")).toBe("Crystal Palace 승");
    expect(legLabel(named[0]!, "HOME")).toBe("Arsenal 승");
    expect(legLabel(named[0]!, "DRAW")).toBe("ARS-CRY 무");
  });

  it("counts selections per league", () => {
    const counts = selectedPerLeague({ 2: "HOME", 3: "AWAY", 1: "DRAW" }, named);
    expect(counts.get(TEST_LEAGUE.id)).toBe(1);
    expect(counts.get(2)).toBe(2);
  });
});
