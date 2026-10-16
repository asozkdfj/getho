import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import type { FixtureDetail, Prediction } from "@edge/contracts";
import { expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  fetchFixtures: vi.fn(),
  fetchLeague: vi.fn(),
  fetchFixture: vi.fn(),
  fetchPrediction: vi.fn(),
  fetchHighlights: vi.fn().mockRejectedValue(new Error("highlights offline")),
  fetchTodayPick: vi.fn().mockResolvedValue(null),
  fetchDataStatus: vi.fn().mockResolvedValue(null),
  fetchLeagues: vi.fn().mockResolvedValue(null),
}));

import { fetchFixture, fetchPrediction, fetchFixtures, fetchLeague } from "@/lib/api";
import sample from "@/lib/codex-qa-fixture.json";
import { Highlights } from "@/components/Highlights";
import { TEST_LEAGUE } from "@/lib/testing";
import FixturesPage from "./page";
import LeaguePage from "./leagues/[id]/page";
import FixturePage from "./fixtures/[id]/page";

it("renders stale-odds quality warnings on the actual detail page", async () => {
  vi.mocked(fetchFixture).mockResolvedValue(sample.fixture as FixtureDetail);
  vi.mocked(fetchPrediction).mockResolvedValue(sample.prediction as Prediction);
  const html = renderToStaticMarkup(
    await FixturePage({ params: Promise.resolve({ id: String(sample.fixture.id) }) }),
  );
  expect(html).toContain("데이터 점검을 통과하지 못한 항목");
  expect(html).toContain("배당 정보 최신 확인 안 됨");
});

it("renders an honest empty highlight explanation", () => {
  const html = renderToStaticMarkup(
    createElement(Highlights, {
      tz: "Asia/Seoul",
      data: {
        items: [],
        note: "QA",
        min_edge: 0.05,
        range_start_utc: "2026-10-16T00:00:00Z",
        range_end_utc: "2026-10-17T00:00:00Z",
      },
    }),
  );
  expect(html).toContain("분석이 있는 예정 경기가 없거나");
  expect(html).not.toContain("비슷하다는 뜻");
});

it("renders both actual async pages when only highlights fail", async () => {
  const fixture = {
    id: 1,
    league: TEST_LEAGUE,
    season: "2026-27",
    round: 1,
    kickoff_at: "2026-10-17T18:00:00Z",
    status: "scheduled" as const,
    home_team: { id: 1, name: "QA_HOME", short_name: "QAH" },
    away_team: { id: 2, name: "QA_AWAY", short_name: "QAA" },
    home_score: null,
    away_score: null,
    lineups_announced: false,
    latest_odds: null,
    prediction_odds: null,
    prediction_id: null,
    model_probabilities: null,
    fair_market_probabilities: null,
  };
  vi.mocked(fetchFixtures).mockResolvedValue({
    fixtures: [fixture],
    data_provider: "mock",
    bookmaker: "mockbook",
    tz: "Asia/Seoul",
    date: "2026-10-17",
    days: 7,
    range_start_utc: "2026-10-16T15:00:00Z",
    range_end_utc: "2026-10-23T15:00:00Z",
  });
  vi.mocked(fetchLeague).mockResolvedValue({
    ...TEST_LEAGUE,
    current_season: "2026-27",
    predicted_count: 1,
    upcoming_count: 1,
  });
  const home = renderToStaticMarkup(await FixturesPage({ searchParams: Promise.resolve({}) }));
  const league = renderToStaticMarkup(await LeaguePage({ params: Promise.resolve({ id: "1" }) }));
  expect(home).toContain("QA_HOME");
  expect(home).toContain("주목할 경기를 불러오지 못했어요");
  expect(league).toContain("QA_HOME");
});
