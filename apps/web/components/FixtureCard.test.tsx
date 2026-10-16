import type { FixtureSummary } from "@edge/contracts";
import { isValidElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TEST_LEAGUE } from "@/lib/testing";

import { FixtureCard } from "./FixtureCard";
import { LocalTime } from "./LocalTime";

/** Props of every element of `type` in a rendered element tree. */
function propsOf(node: ReactNode, type: unknown): Record<string, unknown>[] {
  if (Array.isArray(node)) return node.flatMap((n) => propsOf(n, type));
  if (!isValidElement(node)) return [];
  const props = node.props as Record<string, unknown> & { children?: ReactNode };
  return [...(node.type === type ? [props] : []), ...propsOf(props.children, type)];
}

const fixture: FixtureSummary = {
  id: 7,
  league: TEST_LEAGUE,
  season: "2026-27",
  round: 8,
  kickoff_at: "2026-10-16T15:30:00Z", // 00:30 on the 17th in Seoul
  status: "finished",
  home_team: { id: 1, name: "Arsenal", short_name: "ARS" },
  away_team: { id: 2, name: "Hull City", short_name: "HUL" },
  home_score: 2,
  away_score: 1,
  lineups_announced: false,
};

describe("fixture card", () => {
  it("keeps the kickoff time in the zone its day heading uses (QA-04)", () => {
    const times = propsOf(FixtureCard({ fixture, tz: "Asia/Seoul" }), LocalTime);
    expect(times).toHaveLength(1);
    expect(times[0]).toMatchObject({ format: "time", fixed: true, fallbackTz: "Asia/Seoul" });
    const html = renderToStaticMarkup(<FixtureCard fixture={fixture} tz="Asia/Seoul" />);
    expect(html).toContain("오전 12:30"); // Seoul, not 16:30 of the previous day in London
  });
});
