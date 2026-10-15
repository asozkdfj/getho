import type { Metadata } from "next";

import { CombinationBuilder } from "@/components/CombinationBuilder";
import { Disclaimer } from "@/components/Disclaimer";
import { fetchFixtures } from "@/lib/api";
import { isSelectable } from "@/lib/combination";
import { DEFAULT_TZ } from "@/lib/config";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "조합 분석" };

export default async function CombinationsPage() {
  const tz = DEFAULT_TZ;
  const data = await fetchFixtures({ days: 7, tz });
  const fixtures = data.fixtures.filter(isSelectable);
  return (
    <>
      <h1>조합 분석</h1>
      <p className="muted small">
        서로 다른 경기에서 결과를 2~3개 고르면, 고른 결과가 <strong>모두 맞을 확률</strong>을 분석과
        시장 기준으로 각각 계산해 비교합니다. 경기끼리 서로 영향을 주지 않는다고 보고 계산한
        근사치입니다.
      </p>
      <CombinationBuilder fixtures={fixtures} tz={tz} />
      <Disclaimer />
    </>
  );
}
