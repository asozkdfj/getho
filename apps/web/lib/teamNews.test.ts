import type { TeamNewsSide } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import { positionLabel, reasonLabel, sideSummary } from "./teamNews";

const side = (over: Partial<TeamNewsSide> = {}): TeamNewsSide => ({
  team_id: 1,
  team_name: "Arsenal",
  starters: [],
  absences: [],
  missing_regulars: [],
  regulars_known: true,
  recent_matches: 10,
  ...over,
});

const xi = Array.from({ length: 11 }, (_, i) => ({
  player_id: String(i),
  name: `P${i}`,
  regular: true,
}));

describe("team news wording", () => {
  it("summarises a published line-up against the usual XI", () => {
    expect(sideSummary(side({ starters: xi }))).toBe("평소 주전 11명이 모두 선발로 나와요.");
    const missing = [{ player_id: "9", name: "Saka", reason: "Hamstring Injury" }];
    expect(sideSummary(side({ starters: xi, missing_regulars: missing }))).toBe(
      "평소 주전 11명 중 10명이 선발이에요. 빠진 주전: Saka(부상)",
    );
    expect(sideSummary(side({ starters: xi, regulars_known: false }))).toMatch(/기록은 아직 부족/);
  });

  it("summarises absences before the line-up", () => {
    expect(sideSummary(side())).toBe("아직 알려진 결장 선수가 없어요.");
    const absences = [
      { player_id: "9", name: "Saka", status: "out" as const, reason: "Suspended", regular: true },
    ];
    const missing = [{ player_id: "9", name: "Saka", reason: "Suspended" }];
    expect(sideSummary(side({ absences, missing_regulars: missing }))).toBe(
      "주전 1명 결장 예정: Saka(징계)",
    );
    expect(sideSummary(side({ absences: [{ ...absences[0]!, regular: false }] }))).toMatch(
      /평소 주전은 아님/,
    );
  });

  it("never calls an unknown or doubtful regular a non-regular (QA-07)", () => {
    const doubtful = {
      player_id: "1",
      name: "Player",
      status: "doubtful" as const,
      reason: "Knock",
      regular: false,
    };
    // too little history to know who the regulars are
    expect(sideSummary(side({ absences: [doubtful], regulars_known: false }))).toBe(
      "결장·출전 불투명 1명 (주전인지 판단할 출전 기록이 아직 부족해요)",
    );
    // a known regular who may still play is not in missing_regulars (confirmed only)
    expect(sideSummary(side({ absences: [{ ...doubtful, regular: true }] }))).toBe(
      "주전 1명 출전 불투명: Player(Knock)",
    );
  });

  it("translates positions and common reasons", () => {
    expect(positionLabel("G")).toBe("골키퍼");
    expect(positionLabel(null)).toBe("");
    expect(reasonLabel("Knee Injury")).toBe("부상");
    expect(reasonLabel("Personal reasons")).toBe("Personal reasons");
  });
});
