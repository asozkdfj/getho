import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Disclaimer } from "@/components/Disclaimer";
import { FixtureCard } from "@/components/FixtureCard";
import { Highlights } from "@/components/Highlights";
import { LeagueBadge } from "@/components/LeagueBadge";
import { LeagueMark } from "@/components/LeagueMark";
import { fetchFixtures, fetchHighlights, fetchLeague, orNull } from "@/lib/api";
import { DEFAULT_TZ } from "@/lib/config";
import { leagueNote } from "@/lib/leagues";
import { formatInTz, localDateKey } from "@/lib/time";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

async function load(idParam: string) {
  const id = Number(idParam);
  if (!Number.isInteger(id) || id <= 0) notFound();
  const league = await fetchLeague(id);
  if (!league) notFound();
  return league;
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const league = await load((await params).id);
  return { title: `${league.country_ko} ${league.name}` };
}

export default async function LeaguePage({ params }: { params: Params }) {
  const league = await load((await params).id);
  const tz = DEFAULT_TZ;
  const [data, highlights] = await Promise.all([
    fetchFixtures({ days: 14, tz, leagueId: league.id }),
    league.predicted ? orNull(fetchHighlights({ days: 14, limit: 3, leagueId: league.id })) : null,
  ]);
  const days = new Map<string, typeof data.fixtures>();
  for (const f of data.fixtures) {
    const key = localDateKey(f.kickoff_at, tz);
    days.set(key, [...(days.get(key) ?? []), f]);
  }
  const note = leagueNote(league);

  return (
    <>
      <p className="small">
        <Link href="/leagues">← 리그 목록</Link>
      </p>
      <div className="page-head">
        <div>
          <h1 className="league-h1">
            <LeagueMark league={league} size={28} />
            {league.name}
          </h1>
          <p className="muted small" style={{ margin: 0 }}>
            {league.country_ko}
            {league.current_season && ` · ${league.current_season} 시즌`} ·{" "}
            {league.type === "cup" ? "컵 대회" : "리그"} · 앞으로 14일 {data.fixtures.length}경기
          </p>
          <p style={{ margin: "6px 0 0" }}>
            <LeagueBadge league={league} />
          </p>
        </div>
      </div>
      {note && <p className="card small league-note">{note}</p>}
      {league.verified && (
        <p className="muted small">
          이 리그의 과거 실제 경기로 측정한 결과는{" "}
          <Link href="/performance#leagues">모델 성과</Link>
          에서 볼 수 있어요.
        </p>
      )}

      {highlights && highlights.items.length > 0 && (
        <Highlights data={highlights} tz={tz} title="이 리그에서 주목할 경기" showLeague={false} />
      )}

      <h2>경기 일정</h2>
      {days.size === 0 ? (
        <p className="card">앞으로 14일 안에 예정된 경기가 없어요.</p>
      ) : (
        [...days.entries()].map(([day, fixtures]) => (
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
