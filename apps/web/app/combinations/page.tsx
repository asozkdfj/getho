import type { Metadata } from "next";
import Link from "next/link";

import { CombinationBuilder } from "@/components/CombinationBuilder";
import { Disclaimer } from "@/components/Disclaimer";
import { fetchFixtures, fetchLeagues, orNull } from "@/lib/api";
import { isSelectable } from "@/lib/combination";
import { DEFAULT_TZ } from "@/lib/config";
import { leagueOrder } from "@/lib/leagues";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "조합 분석" };

type Scope = "featured" | "all";

export default async function CombinationsPage({
  searchParams,
}: {
  searchParams: Promise<{ scope?: string }>;
}) {
  const scope: Scope = (await searchParams).scope === "all" ? "all" : "featured";
  const tz = DEFAULT_TZ;
  // Every league over a week is a lot of matches, and odds arrive a few days
  // ahead anyway: "all" covers the next 3 days.
  const days = scope === "all" ? 3 : 7;
  const [data, leagues] = await Promise.all([
    fetchFixtures({ days, tz, featured: scope === "featured" }),
    orNull(fetchLeagues({ days })),
  ]);
  const fixtures = data.fixtures.filter(isSelectable);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>조합 분석</h1>
          <p className="muted small" style={{ margin: 0 }}>
            서로 다른 경기에서 결과를 2~3개 고르면, 고른 결과가 <strong>모두 맞을 확률</strong>을
            분석과 시장 기준으로 각각 계산해 비교합니다. 경기끼리 서로 영향을 주지 않는다고 보고
            계산한 근사치예요.
          </p>
        </div>
        <nav className="tabs" aria-label="리그 범위">
          <Link href="/combinations" aria-current={scope === "featured" ? "page" : undefined}>
            주요 리그 · 7일
          </Link>
          <Link href="/combinations?scope=all" aria-current={scope === "all" ? "page" : undefined}>
            전체 리그 · 3일
          </Link>
        </nav>
      </div>
      <p className="muted small">
        분석과 배당이 모두 있는 경기만 나와요. 리그를 눌러 좁히거나 팀 이름으로 찾을 수 있어요.
      </p>
      <CombinationBuilder key={scope} fixtures={fixtures} tz={tz} order={leagueOrder(leagues)} />
      <Disclaimer />
    </>
  );
}
