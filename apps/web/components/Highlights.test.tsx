import type { Highlight, HighlightList } from "@edge/contracts";
import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TEST_LEAGUE } from "@/lib/testing";

import { Highlights } from "./Highlights";

const list = (items: Highlight[]): HighlightList => ({
  range_start_utc: "2026-10-16T00:00:00Z",
  range_end_utc: "2026-10-23T00:00:00Z",
  min_edge: 0.05,
  items,
  note: "추천이 아닙니다.",
});

const item = (id: number, caveats: Highlight["caveats"]): Highlight => ({
  fixture: {
    id,
    league: { ...TEST_LEAGUE, verified: false },
    season: "2026-27",
    round: 8,
    kickoff_at: "2026-10-17T14:00:00Z",
    status: "scheduled",
    home_team: { id: id * 2, name: `Home ${id}`, short_name: "HOM" },
    away_team: { id: id * 2 + 1, name: `Away ${id}`, short_name: "AWA" },
    home_score: null,
    away_score: null,
    lineups_announced: false,
  },
  outcome: "AWAY",
  model_probability: 0.4,
  fair_probability: 0.28,
  edge: 0.12,
  decimal_odds: 3.4,
  expected_value: 0.36,
  caveats,
});

const render = (data: HighlightList | null) =>
  renderToStaticMarkup(<Highlights data={data} tz="Asia/Seoul" />);

describe("highlights", () => {
  it("shows a failure notice instead of throwing when the request failed (QA-03)", () => {
    const html = render(null);
    expect(html).toContain("주목할 경기를 불러오지 못했어요");
    expect(html).not.toContain("주목할 경기가 없어요");
  });

  it("does not claim model and market agree when the list is empty (QA-06)", () => {
    const html = render(list([]));
    expect(html).toContain("지금 보여 드릴 주목할 경기가 없어요");
    expect(html).not.toMatch(/비슷하다는 뜻/);
  });

  it("shows a caveat shared by every card once, above the cards", () => {
    const html = render(list([item(1, ["unverified_league"]), item(2, ["unverified_league"])]));
    expect(html.match(/정확도 검증 전 리그/g)).toHaveLength(1);
    expect(html).toContain("Home 1");
    expect(html).toContain("Home 2");
  });
});

describe("pages keep the match list when highlights fail (QA-03)", () => {
  // The home and league pages fetch highlights next to the fixtures with
  // Promise.all; an unguarded rejection there would replace the whole page
  // with the error screen. Guard: every highlights fetch is wrapped in orNull.
  for (const page of ["app/page.tsx", "app/leagues/[id]/page.tsx"]) {
    it(page, () => {
      const source = readFileSync(path.join(__dirname, "..", page), "utf8");
      const calls = source.match(/[\w.]*\(?fetchHighlights\(/g) ?? [];
      expect(calls.length).toBeGreaterThan(0);
      expect(calls.every((c) => c.startsWith("orNull("))).toBe(true);
    });
  }
});
