import type { FixtureSummary, LeagueRef, LeagueSummary } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import {
  groupByDayAndLeague,
  groupByLeague,
  leagueBadge,
  leagueLabel,
  leagueNote,
  matchesQuery,
} from "./leagues";
import { TEST_LEAGUE } from "./testing";

const league = (over: Partial<LeagueRef> = {}): LeagueRef => ({ ...TEST_LEAGUE, ...over });

function fixture(id: number, lg: LeagueRef, kickoff: string): FixtureSummary {
  return {
    id,
    league: lg,
    season: "2026-27",
    round: 1,
    kickoff_at: kickoff,
    status: "scheduled",
    home_team: { id: id * 2, name: `H${id}`, short_name: "H" },
    away_team: { id: id * 2 + 1, name: `A${id}`, short_name: "A" },
    home_score: null,
    away_score: null,
  };
}

describe("league badges and notes", () => {
  it("says what the analysis can do in each league", () => {
    expect(leagueBadge(league()).label).toBe("정확도 검증됨");
    expect(leagueBadge(league({ verified: false })).label).toBe("검증 전");
    expect(leagueBadge(league({ predicted: false, verified: false })).label).toBe("분석 준비 중");
    expect(leagueBadge(league({ type: "cup", predicted: false })).label).toBe(
      "컵 대회 · 예측 없음",
    );
  });

  it("explains unverified leagues and cups, and stays quiet for verified ones", () => {
    expect(leagueNote(league())).toBeNull();
    expect(leagueNote(league({ verified: false }))).toMatch(/정확도를 아직 측정하지 않았어요/);
    expect(leagueNote(league({ type: "cup" }))).toMatch(/컵 대회/);
  });

  it("labels a league with its country", () => {
    expect(leagueLabel(league({ country_ko: "대한민국", name: "K League 1" }))).toBe(
      "대한민국 · K League 1",
    );
  });
});

describe("grouping", () => {
  const epl = league({ id: 1, name: "Premier League", featured: true });
  const kl = league({ id: 2, name: "K League 1", featured: false });
  const cup = league({ id: 3, name: "FA Cup", featured: true, type: "cup" });

  it("puts featured leagues first, then the earliest kickoff", () => {
    const groups = groupByLeague([
      fixture(1, kl, "2026-10-17T05:00:00Z"),
      fixture(2, epl, "2026-10-17T14:00:00Z"),
      fixture(3, cup, "2026-10-17T11:00:00Z"),
      fixture(4, epl, "2026-10-17T16:30:00Z"),
    ]);
    expect(groups.map((g) => g.league.name)).toEqual(["FA Cup", "Premier League", "K League 1"]);
    expect(groups[1]!.fixtures.map((f) => f.id)).toEqual([2, 4]);
  });

  it("groups by local day (KST) and then by league", () => {
    const days = groupByDayAndLeague(
      [
        fixture(1, epl, "2026-10-17T14:00:00Z"), // 23:00 KST on the 17th
        fixture(2, epl, "2026-10-17T16:00:00Z"), // 01:00 KST on the 18th
        fixture(3, kl, "2026-10-18T05:00:00Z"),
      ],
      "Asia/Seoul",
    );
    expect(days.map((d) => d.day)).toEqual(["2026-10-17", "2026-10-18"]);
    expect(days[1]!.leagues.map((g) => g.league.id)).toEqual([1, 2]);
  });

  it("searches English and Korean names", () => {
    const lg = {
      ...kl,
      country: "South-Korea",
      country_ko: "대한민국",
      upcoming_count: 3,
      predicted_count: 3,
    } as LeagueSummary;
    expect(matchesQuery(lg, "대한")).toBe(true);
    expect(matchesQuery(lg, "k league")).toBe(true);
    expect(matchesQuery(lg, "spain")).toBe(false);
    expect(matchesQuery(lg, " ")).toBe(true);
  });
});
