import type { Research } from "@edge/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/api", () => ({
  fetchResearch: vi.fn(),
  orNull: async <T,>(p: Promise<T>) => p, // the real helper turns a failed request into null
}));

import { fetchResearch } from "@/lib/api";

import ResearchPage from "./page";

function research(over: Partial<Research> = {}): Research {
  return {
    generated_at: "2026-10-25T01:00:00Z",
    provider: "api_football",
    is_demo: false,
    collection: {
      start: "2026-10-19",
      end: "2026-10-25",
      expected_interval_minutes: 180,
      days_without_decision: ["2026-10-21"],
      days_with_failed_runs: [],
      days_with_long_gaps: [],
      days_with_shadow_errors: [],
      prediction_share: 0.98,
      odds_share: 0.95,
      absences_known_share: 0.6,
      days: [
        {
          day: "2026-10-25",
          decided: true,
          minutes_after_publish_hour: 12,
          runs_success: 8,
          runs_failed: 0,
          runs_expected: 8,
          longest_gap_hours: 3.1,
          fixtures_at_decision: 40,
          with_prediction: 39,
          with_odds: 38,
          shadow_recorded: 37,
          shadow_error: null,
        },
      ],
    },
    shadow: {
      protocol: "shadow-v1",
      window_start: "2026-10-20",
      window_end: "2026-12-14",
      status: "provisional",
      recorded: 300,
      excluded: { no_market_odds: 4 },
      settled: 250,
      pending: 50,
      not_played: 0,
      min_settled: 1500,
      days_with_records: 6,
      no_decision_days: [],
      decision_delay_median_minutes: 14,
      decisions: null,
    },
    live_clv: {
      window_start: "2026-10-20",
      window_end: "2026-10-25",
      counts: { recorded: 300, analysed: 240 },
      analysed: 240,
      days: 6,
      b_model: 0.08,
      b_model_ci: [-0.02, 0.18],
      b_base: 0.3,
      signal: "not_detected",
      share_moves_toward_model: 0.52,
      mean_abs_move: 0.011,
      closing_minutes_before_kickoff_median: 95,
      large_gap: [{ threshold: 0.03, flags: 40, mean_clv: -0.012, share_positive: 0.45 }],
    },
    note: "",
    ...over,
  };
}

beforeEach(() => vi.mocked(fetchResearch).mockReset());

it("shows progress but no shadow scores while the window is open", async () => {
  vi.mocked(fetchResearch).mockResolvedValue(research());
  const html = renderToStaticMarkup(await ResearchPage());
  expect(html).toContain("250");
  expect(html).toContain("1,500");
  expect(html).toContain("성적을 보여 주지 않아요");
  expect(html).not.toContain("log_loss");
  expect(html).toContain("2026-10-21 픽 결정 없음");
  expect(html).toContain("0.080");
  expect(html).toContain("아직 신호 없음");
  expect(html).toContain("실험 기록");
});

it("says when there is nothing to compute yet", async () => {
  const empty = research();
  empty.live_clv = { ...empty.live_clv, analysed: 0, counts: { recorded: 10, before_kickoff: 10 } };
  vi.mocked(fetchResearch).mockResolvedValue(empty);
  const html = renderToStaticMarkup(await ResearchPage());
  expect(html).toContain("아직 계산할 경기가 없어요");
  expect(html).toContain("before_kickoff 10");
});

it("keeps the experiment ledger when the API fails", async () => {
  vi.mocked(fetchResearch).mockResolvedValue(null as unknown as Research);
  const html = renderToStaticMarkup(await ResearchPage());
  expect(html).toContain("불러오지 못했어요");
  expect(html).toContain("승격팀 사전값");
});
