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
        서로 다른 경기에서 2~3개의 결과를 고르면 모델 기준 조합 확률, 시장 공정확률, 조합 배당, EV를
        계산합니다. 조합 확률은 <strong>경기 간 독립을 가정한 근사치</strong>입니다.
      </p>
      <CombinationBuilder fixtures={fixtures} tz={tz} />
      <Disclaimer />
    </>
  );
}
