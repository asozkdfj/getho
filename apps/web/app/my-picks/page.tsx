import type { Metadata } from "next";
import Link from "next/link";

import { LocalTime } from "@/components/LocalTime";
import { PersonalPickForm } from "@/components/PersonalPickForm";
import { fetchFixtures, fetchPersonalPicks, orNull } from "@/lib/api";
import { DEFAULT_TZ } from "@/lib/config";
import { OUTCOME_LABEL, pct, statusLabel } from "@/lib/format";
import { SOURCE_LABEL, selectionProbability } from "@/lib/personalPicks";
import { shiftDate } from "@/lib/review";
import { localDateKey } from "@/lib/time";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "내 픽 기록" };

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export default async function MyPicksPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const tz = DEFAULT_TZ;
  const requested = (await searchParams).date;
  const date =
    requested && DATE.test(requested) ? requested : localDateKey(new Date().toISOString(), tz);
  const [list, fixtures] = await Promise.all([
    orNull(fetchPersonalPicks()),
    orNull(fetchFixtures({ days: 1, tz, date })),
  ]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>내 픽 기록</h1>
          <p className="muted small" style={{ margin: 0 }}>
            내가 고른 경기와 선택을 남기면, 고른 시각까지 알 수 있던 정보로 위험을 정리해 둬요. 모델
            성과와는 따로 저장합니다. 베팅을 실행하지 않아요.
          </p>
        </div>
      </div>

      <section className="stack">
        <div className="section-head">
          <h2>새 기록</h2>
          <nav className="tabs" aria-label="경기 날짜">
            <Link href={`/my-picks?date=${shiftDate(date, -1)}`}>← 전날</Link>
            <span aria-current="page">{date}</span>
            <Link href={`/my-picks?date=${shiftDate(date, 1)}`}>다음날 →</Link>
          </nav>
        </div>
        {fixtures === null ? (
          <p className="error small">경기 목록을 불러오지 못했어요.</p>
        ) : fixtures.fixtures.length === 0 ? (
          <p className="muted small">이 날짜({tz})에는 경기가 없어요.</p>
        ) : (
          <PersonalPickForm mode={{ kind: "create", fixtures: fixtures.fixtures }} tz={tz} />
        )}
      </section>

      <section className="stack" style={{ marginTop: 24 }}>
        <div className="section-head">
          <h2>내 기록</h2>
          {list && (
            <span className="muted small">
              경기 전 기록 {list.counts.prospective_record ?? 0} · 사후 입력{" "}
              {list.counts.retrospective_self_report ?? 0}
            </span>
          )}
        </div>
        {list === null ? (
          <p className="error small">기록을 불러오지 못했어요.</p>
        ) : list.picks.length === 0 ? (
          <p className="muted small">아직 기록이 없어요.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>경기</th>
                  <th>내 선택</th>
                  <th>당시 모델 확률</th>
                  <th>기록 유형</th>
                  <th>경기 상태</th>
                </tr>
              </thead>
              <tbody>
                {list.picks.map((p) => {
                  const prob = selectionProbability(p.current.analysis);
                  return (
                    <tr key={p.pick_id}>
                      <td>
                        <Link href={`/my-picks/${p.pick_id}`}>
                          {p.home_team.name} vs {p.away_team.name}
                        </Link>
                        <div className="muted small">
                          <LocalTime iso={p.kickoff_at} fallbackTz={tz} />
                        </div>
                      </td>
                      <td>{OUTCOME_LABEL[p.current.selection]}</td>
                      <td>{prob === null ? "없음" : pct(prob)}</td>
                      <td>
                        {SOURCE_LABEL[p.current.source_type]}
                        {p.edited_after_kickoff && (
                          <div className="muted small">
                            경기 후 수정 · 경기 전 기록은 {p.prospective_revision}번
                          </div>
                        )}
                      </td>
                      <td>
                        {statusLabel(p.status)}
                        {p.home_score !== null && p.away_score !== null && (
                          <span>
                            {" "}
                            {p.home_score}:{p.away_score}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {list && <p className="muted small">{list.note}</p>}
      </section>
    </>
  );
}
