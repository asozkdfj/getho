import type { FixtureSummary } from "@edge/contracts";
import Link from "next/link";

import { DataStatusBadge } from "@/components/DataStatusBadge";
import { Disclaimer } from "@/components/Disclaimer";
import { FixtureCard } from "@/components/FixtureCard";
import { Highlights } from "@/components/Highlights";
import { TodayPickCard } from "@/components/TodayPickCard";
import { fetchDataStatus, fetchFixtures, fetchHighlights, fetchTodayPick, orNull } from "@/lib/api";
import { DEFAULT_TZ } from "@/lib/config";
import { providerLabel } from "@/lib/format";
import { TERM } from "@/lib/terms";
import { formatInTz, localDateKey } from "@/lib/time";

export const dynamic = "force-dynamic";

type Range = "today" | "week";

function groupByDay(fixtures: FixtureSummary[], tz: string) {
  const groups = new Map<string, FixtureSummary[]>();
  for (const f of fixtures) {
    const key = localDateKey(f.kickoff_at, tz);
    groups.set(key, [...(groups.get(key) ?? []), f]);
  }
  return [...groups.entries()];
}

export default async function FixturesPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string }>;
}) {
  const { range: rawRange } = await searchParams;
  // EPL matches are mostly at weekends, so "today" is usually empty: default to the week.
  const range: Range = rawRange === "today" ? "today" : "week";
  const tz = DEFAULT_TZ;
  const [data, highlights, pick, status] = await Promise.all([
    fetchFixtures({ days: range === "week" ? 7 : 1, tz }),
    fetchHighlights({ days: 7, limit: 3 }),
    orNull(fetchTodayPick()),
    orNull(fetchDataStatus()),
  ]);
  const groups = groupByDay(data.fixtures, tz);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>EPL 경기</h1>
          <p className="muted small" style={{ margin: 0 }}>
            통계 분석과 시장(배당)의 생각을 비교합니다 · 시간대 {tz}
          </p>
          <p className="muted small" style={{ margin: 0 }}>
            데이터: {providerLabel(data.data_provider)} · 배당 출처: {data.bookmaker}
          </p>
          <DataStatusBadge status={status} tz={tz} />
        </div>
      </div>

      <TodayPickCard pick={pick} tz={tz} />

      <Highlights data={highlights} tz={tz} />

      <div className="section-head" id="list">
        <h2>경기 목록</h2>
        <nav className="tabs" aria-label="기간">
          <Link href="/?range=today#list" aria-current={range === "today" ? "page" : undefined}>
            오늘
          </Link>
          <Link href="/?range=week#list" aria-current={range === "week" ? "page" : undefined}>
            이번 주
          </Link>
        </nav>
      </div>
      <div className="legend">
        <span>큰 숫자 = {TERM.model}</span>
        <span>시장 = {TERM.market}</span>
        <span>
          <span className="positive">초록</span>/<span className="negative">빨강</span> = 분석과
          시장의 {TERM.gap}
        </span>
        <Link href="/guide">처음이세요? 3분 가이드 →</Link>
      </div>

      {groups.length === 0 ? (
        <div className="card" style={{ marginTop: 16 }}>
          <p style={{ margin: 0 }}>
            {range === "today" ? "오늘" : "이번 주"} 예정된 경기가 없습니다.{" "}
            {range === "today" && <Link href="/?range=week">이번 주 경기 보기</Link>}
          </p>
          <p className="muted small">
            데이터가 비어 있다면 <code>make seed</code>로 샘플 데이터를 생성하세요.
          </p>
        </div>
      ) : (
        groups.map(([day, fixtures]) => (
          <section key={day} className="day-group">
            <h2>{formatInTz(fixtures[0]!.kickoff_at, tz, "date")}</h2>
            <div className="grid-2">
              {fixtures.map((f) => (
                <FixtureCard key={f.id} fixture={f} tz={tz} />
              ))}
            </div>
          </section>
        ))
      )}

      <Disclaimer />
    </>
  );
}
