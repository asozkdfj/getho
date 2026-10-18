import type { Review, ReviewItem } from "@edge/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/api", () => ({ fetchReview: vi.fn() }));

import { fetchReview } from "@/lib/api";
import { TEST_LEAGUE } from "@/lib/testing";

import ReviewPage from "./page";

// Codex QA F6: the luck note must describe the summary's matches only.
function review(isDemo: boolean): Review {
  const items = Array.from({ length: 110 }, (_, i) => ({
    fixture_id: i + 1,
    league: { ...TEST_LEAGUE, id: i < 10 ? 1 : 2, verified: i < 10 },
    kickoff_at: "2026-10-18T12:00:00Z",
    status: "finished",
    home_team: { id: i * 2, name: `Home ${i}`, short_name: "H" },
    away_team: { id: i * 2 + 1, name: `Away ${i}`, short_name: "A" },
    home_score: 0,
    away_score: 1,
    prediction_id: i + 1,
    model_probabilities: { home: 0.5, draw: 0.25, away: 0.25 },
    market_probabilities: { home: 0.5, draw: 0.25, away: 0.25 },
    top_outcome: "HOME",
    top_probability: 0.5,
    tier: null,
    market_top_outcome: "HOME",
    actual_outcome: "AWAY",
    hit: false,
    market_hit: false,
  })) as ReviewItem[];
  const verified = {
    matches: 10,
    hits: 0,
    expected_hits: 5,
    hit_variance: 2.5,
    market_hits: 0,
    market_expected_hits: 5,
    tiers: {},
  };
  const all = { ...verified, matches: 110, expected_hits: 55, hit_variance: 27.5 };
  return {
    date: "2026-10-18",
    tz: "Asia/Seoul",
    is_demo: isDemo,
    range_start_utc: "2026-10-17T15:00:00Z",
    range_end_utc: "2026-10-18T15:00:00Z",
    items,
    summary: isDemo ? all : verified,
    summary_all: all,
    pick: null,
    note: "QA",
  } as Review;
}

beforeEach(() => vi.mocked(fetchReview).mockReset());

it("judges the verified-league summary by its own spread", async () => {
  vi.mocked(fetchReview).mockResolvedValue(review(false));
  const html = renderToStaticMarkup(await ReviewPage({ searchParams: Promise.resolve({}) }));
  expect(html).toContain("0 / 10");
  expect(html).toContain("기대보다 꽤 적게 맞았어요");
  expect(html).not.toContain("확률로 보면 흔히 나오는 범위예요");
});

it("uses every league on demo data", async () => {
  vi.mocked(fetchReview).mockResolvedValue(review(true));
  const html = renderToStaticMarkup(await ReviewPage({ searchParams: Promise.resolve({}) }));
  expect(html).toContain("0 / 110");
  expect(html).toContain("기대보다 꽤 적게 맞았어요");
  expect(html).toContain("데모 데이터");
});
