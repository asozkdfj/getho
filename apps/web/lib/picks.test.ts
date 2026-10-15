import type { CalibrationBin, PickHistory, TodayPick } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import {
  backtestScope,
  closestCandidate,
  excludedReasonText,
  historySummaryText,
  periodText,
  pickCautions,
  pickReasons,
  pickStatusInfo,
  qualityCheckLabel,
  rateWithCi,
  reliabilityPoints,
  thresholdText,
  voidReasonText,
} from "./picks";
import { TEST_LEAGUE } from "./testing";

const pick: TodayPick = {
  date: "2026-10-17",
  tz: "Asia/Seoul",
  status: "published",
  is_demo: false,
  publish_at: "2026-10-17T00:00:00Z",
  threshold: 0.55,
  league_scope: "verified",
  pick_id: 1,
  revision: 1,
  published_at: "2026-10-17T00:00:05Z",
  fixture: {
    id: 7,
    league: TEST_LEAGUE,
    season: "2026-27",
    round: 8,
    kickoff_at: "2026-10-17T14:00:00Z",
    status: "scheduled",
    home_team: { id: 1, name: "Arsenal", short_name: "ARS" },
    away_team: { id: 2, name: "Hull City", short_name: "HUL" },
    home_score: null,
    away_score: null,
  },
  outcome: "HOME",
  probability: 0.68,
  probabilities: { home: 0.68, draw: 0.19, away: 0.13 },
  expected_goals: { home: 2.1, away: 0.8 },
  factors_used: ["team_strength_elo", "attack_defence_strength", "home_advantage"],
  features: {
    elo_home: 1712.4,
    elo_away: 1401.2,
    elo_diff_incl_hfa: 371.2,
    attack_home: 1.42,
    defence_home: 0.71,
    attack_away: 0.82,
    defence_away: 1.25,
    prior_home: "observed",
    prior_away: "promoted_relegation_level",
  },
  quality_checks: [],
  candidates: [],
  disclaimer: "확률은 추정치입니다.",
};

describe("Today's Pick explanation", () => {
  it("cites only the model's own inputs", () => {
    const reasons = pickReasons(pick);
    expect(reasons[0]).toBe(
      "전력 점수(Elo): Arsenal 1712 · Hull City 1401 — Arsenal의 누적 전력이 더 높아요.",
    );
    expect(reasons[1]).toBe("홈 경기 이점(전력 점수 +60)을 Arsenal에 더해 계산했어요.");
    expect(reasons[2]).toMatch(/Arsenal 득점력 1\.42, 실점 0\.71, Hull City 득점력 0\.82/);
    expect(reasons[3]).toBe("이를 합쳐 예상 골은 Arsenal 2.10 : 0.80 Hull City로 계산됐어요.");
  });

  it("does not overstate a tiny strength gap", () => {
    const close = { ...pick, features: { ...pick.features, elo_home: 1592, elo_away: 1590 } };
    expect(pickReasons(close)[0]).toMatch(/두 팀의 누적 전력은 비슷해요/);
  });

  it("drops a factor the model did not use", () => {
    const reasons = pickReasons({ ...pick, factors_used: ["attack_defence_strength"] });
    expect(reasons.some((r) => r.includes("Elo"))).toBe(false);
    expect(reasons.some((r) => r.includes("홈 경기 이점"))).toBe(false);
  });

  it("explains nothing when there is no pick", () => {
    expect(pickReasons({ ...pick, fixture: null, outcome: null })).toEqual([]);
  });

  it("warns about newcomers and missing news", () => {
    const cautions = pickCautions(pick);
    expect(cautions[0]).toMatch(/^Hull City: 승격팀/);
    expect(cautions.at(-1)).toMatch(/부상·이적/);
  });

  it("never uses guaranteeing words", () => {
    const text = [...pickReasons(pick), ...pickCautions(pick)].join(" ");
    expect(text).not.toMatch(/확실|보장|무조건|필승/);
  });
});

describe("status and labels", () => {
  it("explains no-pick days with the configured threshold", () => {
    expect(pickStatusInfo("no_qualifying_match", 0.55).description).toMatch(/55%/);
    expect(pickStatusInfo("voided", 0.55).tone).toBe("negative");
  });

  it("maps every reason and check name", () => {
    expect(excludedReasonText("below_min_probability")).toBe("기준 확률 미달");
    expect(excludedReasonText("unknown_reason")).toBe("unknown_reason");
    expect(qualityCheckLabel("odds_fresh")).toBe("배당 정보 최신");
    expect(voidReasonText("fixture postponed")).toBe("경기 연기");
    expect(voidReasonText(null)).toBe("");
  });

  it("formats rates with their range", () => {
    expect(rateWithCi(0.714, [0.653, 0.768])).toBe("71% (65%–77%)");
    expect(rateWithCi(null, null)).toBe("–");
  });

  it("describes a zero threshold as no threshold", () => {
    expect(thresholdText(0)).toBe("기준 확률 없음");
    expect(thresholdText(0.55)).toBe("기준 55%");
  });

  it("names the leagues pooled in the backtest", () => {
    expect(backtestScope(["Premier League"])).toBe("실제 Premier League 경기");
    expect(backtestScope(["A", "B", "C"])).toBe("검증된 3개 리그의 실제 경기");
    expect(backtestScope([])).toBe("실제 경기");
  });

  it("describes report periods in words", () => {
    expect(periodText(">= 2023-24")).toBe("2023-24 시즌부터 지금까지");
    expect(periodText("2020-21 .. < 2023-24")).toBe("2020-21 시즌부터 2023-24 시즌 전까지");
    expect(periodText(null)).toBe("과거");
  });
});

describe("history summary", () => {
  const history = (settled: number, hits: number): PickHistory => ({
    is_demo: false,
    items: [],
    note: "",
    summary: {
      published: settled,
      settled,
      voided: 0,
      pending: 0,
      hits,
      hit_rate: settled ? hits / settled : null,
      hit_rate_ci: settled ? [0.2, 0.9] : null,
      mean_probability: settled ? 0.64 : null,
    },
  });

  it("waits for results before reporting a hit rate", () => {
    expect(historySummaryText(history(0, 0))).toMatch(/아직 결과가 나온 픽이 없어요/);
  });

  it("flags small samples", () => {
    expect(historySummaryText(history(10, 7))).toMatch(/10개 중 7개 적중.*표본이 작아/);
    expect(historySummaryText(history(40, 26))).not.toMatch(/표본이 작아/);
  });
});

describe("reliability points", () => {
  it("keeps non-empty bins of one outcome", () => {
    const bins: CalibrationBin[] = [
      {
        outcome: "HOME",
        lower: 0,
        upper: 0.1,
        count: 0,
        mean_predicted: null,
        observed_frequency: null,
      },
      {
        outcome: "HOME",
        lower: 0.4,
        upper: 0.5,
        count: 30,
        mean_predicted: 0.45,
        observed_frequency: 0.5,
      },
      {
        outcome: "AWAY",
        lower: 0.4,
        upper: 0.5,
        count: 9,
        mean_predicted: 0.44,
        observed_frequency: 0.3,
      },
    ];
    expect(reliabilityPoints(bins, "HOME")).toEqual([
      { predicted: 0.45, observed: 0.5, count: 30 },
    ]);
  });
});

describe("no-pick day", () => {
  it("names the strongest candidate that only missed the threshold", () => {
    const day: TodayPick = {
      ...pick,
      status: "no_qualifying_match",
      fixture: null,
      outcome: null,
      probability: null,
      candidates: [
        {
          fixture_id: 1,
          home: "Wolves",
          away: "Newcastle",
          kickoff_at: "2026-10-15T15:00:00Z",
          best_outcome: null,
          best_probability: null,
          eligible: false,
          excluded_reasons: ["upcoming", "prediction_available"],
        },
        {
          fixture_id: 2,
          home: "Chelsea",
          away: "Arsenal",
          kickoff_at: "2026-10-16T12:30:00Z",
          best_outcome: "HOME",
          best_probability: 0.443,
          eligible: false,
          excluded_reasons: ["below_min_probability"],
        },
      ],
    };
    expect(closestCandidate(day)).toBe(
      "오늘 가장 높았던 분석 확률: Chelsea vs Arsenal — Chelsea 승리 44% (기준 55%)",
    );
    expect(closestCandidate({ ...day, candidates: [day.candidates![0]!] })).toBeNull();
  });
});
