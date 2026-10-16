import type { Region } from "@edge/contracts";
import type { Metadata } from "next";
import Link from "next/link";

import { LeagueBadge } from "@/components/LeagueBadge";
import { LeagueChips } from "@/components/LeagueChips";
import { LeagueMark } from "@/components/LeagueMark";
import { fetchLeagues } from "@/lib/api";
import { matchesQuery } from "@/lib/leagues";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "리그" };

export default async function LeaguesPage({
  searchParams,
}: {
  searchParams: Promise<{ region?: string; q?: string }>;
}) {
  const { region: rawRegion, q = "" } = await searchParams;
  const data = await fetchLeagues({ days: 7 });
  const region = data.regions.find((r) => r.region === rawRegion)?.region as Region | undefined;
  const regions = data.regions
    .filter((r) => !region || r.region === region)
    .map((r) => ({
      ...r,
      countries: r.countries
        .map((c) => ({ ...c, leagues: c.leagues.filter((lg) => matchesQuery(lg, q)) }))
        .filter((c) => c.leagues.length > 0),
    }))
    .filter((r) => r.countries.length > 0);
  const regionHref = (r?: string) => {
    const p = new URLSearchParams();
    if (r) p.set("region", r);
    if (q) p.set("q", q);
    const s = p.toString();
    return `/leagues${s ? `?${s}` : ""}`;
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>리그</h1>
          <p className="muted small" style={{ margin: 0 }}>
            앞으로 7일 안에 경기가 있는 리그 {data.total_leagues}개 · 지역과 나라별로 모았어요
          </p>
        </div>
      </div>

      {data.featured.length > 0 && (
        <>
          <h2>주요 리그</h2>
          <LeagueChips leagues={data.featured} more={false} />
        </>
      )}

      <form className="league-search" action="/leagues" method="get" role="search">
        {region && <input type="hidden" name="region" value={region} />}
        <input
          type="search"
          name="q"
          defaultValue={q}
          placeholder="리그·나라 검색 (예: 스페인)"
          aria-label="리그 검색"
        />
        <button type="submit" className="btn secondary">
          검색
        </button>
      </form>

      <nav className="league-chips" aria-label="지역">
        <Link href={regionHref()} className="chip" aria-current={!region ? "page" : undefined}>
          전체
        </Link>
        {data.regions.map((r) => (
          <Link
            key={r.region}
            href={regionHref(r.region)}
            className="chip"
            aria-current={region === r.region ? "page" : undefined}
          >
            {r.region_ko}
          </Link>
        ))}
      </nav>

      {regions.length === 0 ? (
        <p className="card">
          {q ? `'${q}'에 맞는 리그가 없어요.` : "앞으로 7일 안에 경기가 있는 리그가 없어요."}
        </p>
      ) : (
        regions.map((r) => (
          <section key={r.region}>
            <h2>{r.region_ko}</h2>
            <div className="country-grid">
              {r.countries.map((c) => (
                <div key={c.country} className="card country-card">
                  <h3>{c.country_ko}</h3>
                  <ul className="league-list">
                    {c.leagues.map((lg) => (
                      <li key={lg.id}>
                        <Link href={`/leagues/${lg.id}`} className="league-row">
                          <span className="league-row-name">
                            <LeagueMark league={lg} />
                            {lg.name}
                          </span>
                          <span className="muted small">{lg.upcoming_count}경기</span>
                        </Link>
                        <LeagueBadge league={lg} />
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>
        ))
      )}

      <p className="muted small">
        <strong>정확도 검증됨</strong>: 과거 실제 경기로 분석의 정확도를 측정한 리그 ·{" "}
        <strong>검증 전</strong>: 같은 방식으로 분석하지만 정확도는 아직 측정하지 않은 리그 ·{" "}
        <strong>컵 대회</strong>: 여러 리그 팀이 섞여 있어 예측하지 않아요.{" "}
        <Link href="/performance#leagues">리그별 성과 보기</Link>
      </p>
    </>
  );
}
