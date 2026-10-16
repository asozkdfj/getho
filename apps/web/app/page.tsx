import Link from "next/link";

import { DataStatusBadge } from "@/components/DataStatusBadge";
import { Disclaimer } from "@/components/Disclaimer";
import { FixtureCard } from "@/components/FixtureCard";
import { Highlights } from "@/components/Highlights";
import { LeagueChips } from "@/components/LeagueChips";
import { LeagueHeader } from "@/components/LeagueHeader";
import { TodayPickCard } from "@/components/TodayPickCard";
import {
  fetchDataStatus,
  fetchFixtures,
  fetchHighlights,
  fetchLeagues,
  fetchTodayPick,
  orNull,
} from "@/lib/api";
import { DEFAULT_TZ } from "@/lib/config";
import { providerLabel } from "@/lib/format";
import { groupByDayAndLeague, leagueOrder } from "@/lib/leagues";
import { TERM } from "@/lib/terms";
import { dayLabel, formatInTz } from "@/lib/time";

export const dynamic = "force-dynamic";

type Range = "today" | "week";
type Scope = "featured" | "all";

function href(range: Range, scope: Scope) {
  const q = new URLSearchParams();
  if (range === "today") q.set("range", "today");
  if (scope === "all") q.set("scope", "all");
  const s = q.toString();
  return `/${s ? `?${s}` : ""}#list`;
}

export default async function FixturesPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string; scope?: string }>;
}) {
  const params = await searchParams;
  const scope: Scope = params.scope === "all" ? "all" : "featured";
  // Every league at once is a lot of matches: "all" shows today only.
  // Major leagues mostly play at weekends, so their default is the week.
  const range: Range = scope === "all" || params.range === "today" ? "today" : "week";
  const tz = DEFAULT_TZ;
  const [data, highlights, pick, status, leagues] = await Promise.all([
    fetchFixtures({ days: range === "week" ? 7 : 1, tz, featured: scope === "featured" }),
    orNull(fetchHighlights({ days: 7, limit: 3 })),
    orNull(fetchTodayPick()),
    orNull(fetchDataStatus()),
    orNull(fetchLeagues({ days: 7 })),
  ]);
  const groups = groupByDayAndLeague(data.fixtures, tz, leagueOrder(leagues));
  const featured = leagues?.featured ?? [];
  const others = (leagues?.regions ?? [])
    .flatMap((r) => r.countries.flatMap((c) => c.leagues))
    .filter((lg) => !lg.featured)
    .sort((a, b) => b.upcoming_count - a.upcoming_count)
    .slice(0, 12);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>축구 경기</h1>
          <p className="muted small" style={{ margin: 0 }}>
            리그별로 통계 분석과 시장(배당)의 생각을 비교합니다 · 시간대 {tz}
          </p>
          <p className="muted small" style={{ margin: 0 }}>
            데이터: {providerLabel(data.data_provider)} · 배당 출처: {data.bookmaker}
            {leagues && ` · 이번 주 경기가 있는 리그 ${leagues.total_leagues}개`}
          </p>
          <DataStatusBadge status={status} tz={tz} />
        </div>
      </div>

      <TodayPickCard pick={pick} tz={tz} />

      {featured.length > 0 && <LeagueChips leagues={featured} />}

      <Highlights data={highlights} tz={tz} />

      <div className="section-head" id="list">
        <h2>경기 목록</h2>
        <div className="section-tools">
          <nav className="tabs" aria-label="리그 범위">
            <Link
              href={href(range, "featured")}
              aria-current={scope === "featured" ? "page" : undefined}
            >
              주요 리그
            </Link>
            <Link href={href("today", "all")} aria-current={scope === "all" ? "page" : undefined}>
              전체 리그
            </Link>
          </nav>
          {scope === "featured" && (
            <nav className="tabs" aria-label="기간">
              <Link
                href={href("today", scope)}
                aria-current={range === "today" ? "page" : undefined}
              >
                오늘
              </Link>
              <Link href={href("week", scope)} aria-current={range === "week" ? "page" : undefined}>
                이번 주
              </Link>
            </nav>
          )}
        </div>
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
      {scope === "all" && (
        <p className="muted small">전체 리그는 경기가 많아 오늘 경기만 보여 드려요.</p>
      )}
      {groups.length > 1 && (
        <nav className="league-chips day-chips" aria-label="날짜 바로가기">
          {groups.map((day) => (
            <a key={day.day} href={`#day-${day.day}`} className="chip">
              {dayLabel(day.first, tz)}
              <span className="chip-count">
                {day.leagues.reduce((n, g) => n + g.fixtures.length, 0)}
              </span>
            </a>
          ))}
        </nav>
      )}

      {groups.length === 0 ? (
        <div className="card" style={{ marginTop: 16 }}>
          <p style={{ margin: 0 }}>
            {range === "today" ? "오늘" : "이번 주"} {scope === "featured" ? "주요 리그에 " : ""}
            예정된 경기가 없습니다.{" "}
            {scope === "featured" && <Link href={href("today", "all")}>전체 리그 보기</Link>}
          </p>
          <p className="muted small">
            데이터가 비어 있다면 <code>make seed</code>로 샘플 데이터를 생성하세요.
          </p>
        </div>
      ) : (
        groups.map((day) => (
          <section key={day.day} className="day-group" id={`day-${day.day}`}>
            <h2>{formatInTz(day.first, tz, "date")}</h2>
            {day.leagues.map((g) => (
              <div key={g.league.id} className="league-group">
                <LeagueHeader league={g.league} count={g.fixtures.length} />
                <div className="grid-2">
                  {g.fixtures.map((f) => (
                    <FixtureCard key={f.id} fixture={f} tz={tz} />
                  ))}
                </div>
              </div>
            ))}
          </section>
        ))
      )}

      {others.length > 0 && (
        <section>
          <h2>다른 리그</h2>
          <LeagueChips leagues={others} />
        </section>
      )}

      <Disclaimer />
    </>
  );
}
