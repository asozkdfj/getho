import type { PickAnalysis } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import {
  EMPTY_FORM,
  cautionLines,
  createBody,
  newRequestKey,
  revisionBody,
  riskLines,
  zonedToIso,
} from "./personalPicks";

const side = (team_name: string) => ({
  team_name,
  absences_status: "unknown" as const,
  absences: [],
  missing_regulars: [],
  regulars_known: false,
});

const analysis = (over: Partial<PickAnalysis> = {}): PickAnalysis => ({
  version: "personal-pick-r1-2026-10-21",
  as_of: "2026-10-21T10:00:00Z",
  computed_at: "2026-10-21T10:00:00Z",
  selection: "AWAY",
  home_team: "Arsenal",
  away_team: "Chelsea",
  league_name: "Premier League",
  league_verified: true,
  kickoff_at: "2026-10-21T19:00:00Z",
  model: {
    prediction_id: 1,
    model_version: "1.0.0",
    prediction_created_at: "2026-10-21T09:00:00Z",
    input_data_as_of: "2026-10-21T09:00:00Z",
    probabilities: { home: 0.55, draw: 0.25, away: 0.2 },
    selection_probability: 0.2,
    failure_probability: 0.8,
    failure_outcomes: [
      { outcome: "HOME", probability: 0.55 },
      { outcome: "DRAW", probability: 0.25 },
    ],
    top_outcome: "HOME",
    top_probability: 0.55,
    agrees_with_top: false,
  },
  market: null,
  price: null,
  team_news: {
    lineups_announced: false,
    home: side("Arsenal"),
    away: side("Chelsea"),
    snapshot_ids: [],
  },
  warnings: [],
  missing: [],
  ...over,
});

describe("request building", () => {
  it("keeps empty inputs empty instead of sending 0", () => {
    const r = createBody(7, "k".repeat(16), { ...EMPTY_FORM, selection: "AWAY" }, "Asia/Seoul");
    expect(r.error).toBeNull();
    expect(r.body).toEqual({
      selection: "AWAY",
      self_reported_purchase: false,
      idempotency_key: "k".repeat(16),
      fixture_id: 7,
    });
  });

  it("converts the inputs and refuses bad ones", () => {
    const v = {
      ...EMPTY_FORM,
      selection: "HOME" as const,
      entryOdds: "2.15",
      stakeKrw: "10,000",
      userProbabilityPct: "48",
      reason: "  홈 공격 좋음 ",
    };
    const r = revisionBody(2, "key-12345678", v, "Asia/Seoul");
    expect(r.body).toMatchObject({
      base_revision: 2,
      entry_odds: 2.15,
      stake_krw: 10000,
      user_probability: 0.48,
      user_reason: "홈 공격 좋음",
    });
    expect(createBody(1, "k", { ...EMPTY_FORM }, "UTC").error).toMatch(/하나를 고르세요/);
    expect(createBody(1, "k", { ...v, entryOdds: "1" }, "UTC").error).toMatch(/1보다 큰/);
    expect(createBody(1, "k", { ...v, entryOdds: "2.155" }, "UTC").error).toMatch(/둘째 자리/);
    expect(createBody(1, "k", { ...v, userProbabilityPct: "100" }, "UTC").error).toMatch(/0과 100/);
    expect(createBody(1, "k", { ...v, stakeKrw: "-5" }, "UTC").error).toMatch(/0 이상/);
    expect(createBody(1, "k", { ...v, decidedNow: false }, "UTC").error).toMatch(/결정 시각/);
  });

  it("reads the decision time in the page's time zone", () => {
    expect(zonedToIso("2026-10-21T19:30", "Asia/Seoul")).toBe("2026-10-21T10:30:00.000Z");
    expect(zonedToIso("2026-07-01T12:00", "Europe/London")).toBe("2026-07-01T11:00:00.000Z");
    expect(zonedToIso("2026-12-01T12:00", "Europe/London")).toBe("2026-12-01T12:00:00.000Z");
    expect(zonedToIso("not a time", "UTC")).toBeNull();
  });

  it("makes a key without crypto.randomUUID (plain http)", () => {
    const key = newRequestKey((a) => a.fill(171));
    expect(key).toBe("ab".repeat(16));
    expect(newRequestKey()).toMatch(/^[0-9a-f]{32}$/);
  });
});

describe("analysis texts", () => {
  it("states the risk of the user's selection, not the model's", () => {
    const lines = riskLines(analysis());
    expect(lines[0]).toMatch(
      /원정 승 확률 20\.0%.*빗나갈 확률 80\.0%.*홈 승 55\.0%, 무승부 25\.0%/,
    );
    expect(lines[1]).toMatch(/가장 높게 본 결과는 홈 승 55\.0%/);
  });

  it("labels the return as a model-assumption estimate", () => {
    const lines = riskLines(
      analysis({
        price: {
          entry_odds: 4.5,
          break_even_probability: 1 / 4.5,
          model_assumption_return: -0.1,
          market_assumption_return: null,
        },
      }),
    );
    expect(lines.at(-1)).toMatch(
      /손익분기 확률은 22\.2%.*모델이 맞다는 가정의 기대수익 추정 −10\.0%/,
    );
  });

  it("says what is missing instead of guessing", () => {
    const lines = cautionLines(
      analysis({
        model: null,
        missing: [
          { item: "model", reason: "no_prediction_known_at_decision" },
          { item: "entry_odds", reason: "not_entered" },
          { item: "absences_away", reason: "not_checked" },
        ],
        warnings: ["absences_unknown_away", "league_not_verified"],
      }),
    );
    expect(lines.join("\n")).toMatch(/모델 예측이 없어/);
    expect(lines.join("\n")).toMatch(/Chelsea 결장 정보.*미확인/);
    expect(lines.join("\n")).toMatch(/검증하지 않은 리그/);
    expect(riskLines(analysis({ model: null }))).toEqual([]);
  });
});
