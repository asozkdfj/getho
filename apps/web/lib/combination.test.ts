import type { FixtureSummary } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import {
  blockReason,
  isSelectable,
  legLabel,
  matchesTeam,
  oddsUpdatedSincePrediction,
  pricedOdds,
  requestAnalysis,
  selectedLegs,
  selectedPerLeague,
  toRequest,
  toggleSelection,
} from "./combination";
import { LatestRequest } from "./latestRequest";
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
    prediction_odds: {
      id: id * 10,
      bookmaker: "mockbook",
      market: "1X2",
      odds_home: 2,
      odds_draw: 3.4,
      odds_away: 3.8,
      captured_at: "2026-10-15T06:30:00Z",
    },
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
    expect(isSelectable(fx(9, 10, 11, { prediction_odds: null }))).toBe(false);
    // newer market odds do not matter: the combination is priced on the prediction's odds
    expect(isSelectable(fx(9, 10, 11, { latest_odds: null }))).toBe(true);
    expect(blockReason({}, fx(9, 10, 11, { prediction_id: null }), all)).toMatch(/예측/);
  });

  it("builds the API request body", () => {
    expect(toRequest({ 1: "HOME", 2: "AWAY" }, [])).toEqual({
      selections: [
        { fixture_id: 1, outcome: "HOME" },
        { fixture_id: 2, outcome: "AWAY" },
      ],
    });
  });

  it("sends the prediction the user saw, so a replaced price is refused (Codex F1)", () => {
    const shown = [
      { id: 1, prediction_id: 41 },
      { id: 2, prediction_id: null },
    ];
    expect(toRequest({ 1: "HOME", 2: "AWAY" }, shown)).toEqual({
      selections: [
        { fixture_id: 1, outcome: "HOME", prediction_id: 41 },
        { fixture_id: 2, outcome: "AWAY" },
      ],
    });
  });
});

describe("priced odds (QA-02)", () => {
  it("flags odds that arrived after the prediction", () => {
    const fresh = fx(1, 1, 2);
    expect(oddsUpdatedSincePrediction(fresh)).toBe(false);
    const stale = fx(1, 1, 2, { latest_odds: { ...fresh.latest_odds!, id: 999, odds_home: 2.4 } });
    expect(oddsUpdatedSincePrediction(stale)).toBe(true);
    expect(pricedOdds(stale)?.odds_home).toBe(2);
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

describe("analysis requests racing (QA-01)", () => {
  /** A fetch whose answers the test releases in any order. */
  function controllableFetch() {
    const pending: { resolve: (r: Response) => void; reject: (e: unknown) => void }[] = [];
    const impl = ((_url: string, init?: RequestInit) =>
      new Promise<Response>((resolve, reject) => {
        pending.push({ resolve, reject });
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted")));
      })) as unknown as typeof fetch;
    const answer = (i: number, body: unknown, status = 200) =>
      pending[i]!.resolve(new Response(JSON.stringify(body), { status }));
    return { impl, answer };
  }

  it("ignores the older answer when a newer request was started", async () => {
    const guard = new LatestRequest();
    const { impl, answer } = controllableFetch();
    const first = requestAnalysis({ 1: "HOME", 2: "AWAY" }, guard.start(), [], impl);
    const second = requestAnalysis({ 1: "DRAW", 3: "AWAY" }, guard.start(), [], impl);
    answer(1, { model_probability: 0.2 });
    answer(0, { model_probability: 0.9 }); // too late, and already aborted
    expect(await second).toEqual({ kind: "result", combination: { model_probability: 0.2 } });
    expect(await first).toEqual({ kind: "stale" });
  });

  it("drops an answer that arrives after the selection was reset", async () => {
    const guard = new LatestRequest();
    const { impl, answer } = controllableFetch();
    const running = requestAnalysis({ 1: "HOME", 2: "AWAY" }, guard.start(), [], impl);
    guard.cancel(); // the user changed or cleared the selection
    answer(0, { model_probability: 0.5 });
    expect(await running).toEqual({ kind: "stale" }); // no result, no error, no scroll
  });

  it("drops an answer already received when the selection changes", async () => {
    // The response is in, its body not yet read: aborting can no longer stop
    // it, so only the ticket check keeps the old result off the screen.
    const guard = new LatestRequest();
    const { impl, answer } = controllableFetch();
    const running = requestAnalysis({ 1: "HOME", 2: "AWAY" }, guard.start(), [], impl);
    answer(0, { model_probability: 0.5 });
    guard.cancel();
    expect(await running).toEqual({ kind: "stale" });
  });

  it("reports API errors and network failures for the current request only", async () => {
    const guard = new LatestRequest();
    const { impl, answer } = controllableFetch();
    const rejected = requestAnalysis({ 1: "HOME", 2: "AWAY" }, guard.start(), [], impl);
    answer(0, { detail: "같은 경기를 두 번 고를 수 없습니다" }, 422);
    expect(await rejected).toEqual({
      kind: "error",
      message: "같은 경기를 두 번 고를 수 없습니다",
    });
    const outdated = requestAnalysis({ 1: "HOME", 2: "AWAY" }, guard.start(), [], impl);
    answer(1, { detail: "선택한 뒤 분석(배당)이 갱신된 경기가 있습니다." }, 409);
    expect(await outdated).toEqual({
      kind: "outdated",
      message: "선택한 뒤 분석(배당)이 갱신된 경기가 있습니다.",
    });
    const failing = (() => Promise.reject(new TypeError("network"))) as unknown as typeof fetch;
    expect(await requestAnalysis({ 1: "HOME" }, guard.start(), [], failing)).toEqual({
      kind: "error",
      message: "API에 연결할 수 없습니다. 잠시 후 다시 시도하세요.",
    });
  });
});
