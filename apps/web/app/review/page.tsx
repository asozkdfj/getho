import type { Review, ReviewItem } from "@edge/contracts";
import type { Metadata } from "next";
import Link from "next/link";

import { Disclaimer } from "@/components/Disclaimer";
import { LocalTime } from "@/components/LocalTime";
import { fetchReview } from "@/lib/api";
import { OUTCOME_LABEL, pct } from "@/lib/format";
import {
  luckNote,
  marketText,
  resultTag,
  reviewSummaryText,
  shiftDate,
  topLabel,
} from "@/lib/review";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "경기 복기" };

const DATE = /^\d{4}-\d{2}-\d{2}$/;

function byLeague(items: ReviewItem[]) {
  const groups = new Map<number, { name: string; country: string; items: ReviewItem[] }>();
  for (const i of items) {
    const g = groups.get(i.league.id) ?? {
      name: i.league.name,
      country: i.league.country_ko,
      items: [],
    };
    g.items.push(i);
    groups.set(i.league.id, g);
  }
  return [...groups.values()];
}

function PickLine({ data }: { data: Review }) {
  const p = data.pick;
  if (!p) return <span className="muted">기록 없음</span>;
  if (p.status === "no_qualifying_match" || p.status === "no_matches") {
    return <span className="muted">고르지 않은 날</span>;
  }
  const label = p.outcome ? `${OUTCOME_LABEL[p.outcome]} ${pct(p.probability, 0)}` : "";
  if (p.hit === true) return <span className="positive">{label} · 적중</span>;
  if (p.hit === false) return <span className="negative">{label} · 빗나감</span>;
  return (
    <span>
      {label} · {p.status === "voided" ? "무효" : "결과 전"}
    </span>
  );
}

export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const requested = (await searchParams).date;
  const data = await fetchReview(requested && DATE.test(requested) ? requested : undefined);
  const s = data.summary;
  const high = s.tiers.high;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>경기 복기</h1>
          <p className="muted small" style={{ margin: 0 }}>
            경기 전에 분석이 말한 확률과 실제 결과를 나란히 봐요. 경기 시작 전 정보로 만든 분석만
            씁니다.
          </p>
        </div>
        <nav className="tabs" aria-label="날짜 이동">
          <Link href={`/review?date=${shiftDate(data.date, -1)}`}>← 전날</Link>
          <span aria-current="page">{data.date}</span>
          <Link href={`/review?date=${shiftDate(data.date, 1)}`}>다음날 →</Link>
        </nav>
      </div>
      {data.is_demo && (
        <p className="demo-banner small">
          데모 데이터(합성 경기)의 기록입니다. 실제 성과로 해석하지 마세요.
        </p>
      )}

      <div className="stat-grid">
        <div className="stat">
          <div className="label">분석 1순위 적중</div>
          <div className="value">
            {s.hits} / {s.matches}
          </div>
          <div className="muted small">기대 약 {s.expected_hits.toFixed(1)}개</div>
        </div>
        <div className="stat">
          <div className="label">시장 1순위 적중</div>
          <div className="value">
            {s.market_hits} / {s.matches}
          </div>
          <div className="muted small">기대 약 {s.market_expected_hits.toFixed(1)}개</div>
        </div>
        <div className="stat">
          <div className="label">확률 높음(65%+) 경기</div>
          <div className="value">{high ? `${high.hits} / ${high.matches}` : "–"}</div>
          {high && high.matches > 0 && (
            <div className="muted small">기대 약 {high.expected_hits.toFixed(1)}개</div>
          )}
        </div>
        <div className="stat">
          <div className="label">그날의 오늘의 픽</div>
          <div className="value small-value">
            <PickLine data={data} />
          </div>
        </div>
      </div>
      <p className="small">
        {reviewSummaryText(s)} {marketText(s)}
      </p>
      <p className="muted small">
        {luckNote(s)} {data.note}
        {!data.is_demo && " 위 숫자는 정확도를 검증한 리그 경기만 셉니다."}
      </p>

      {data.items.length === 0 ? (
        <p className="card small">이 날 경기가 없어요.</p>
      ) : (
        byLeague(data.items).map((g) => (
          <section key={g.name} className="review-group">
            <h2 className="review-league">
              <span className="muted">{g.country} · </span>
              {g.name}
            </h2>
            <ul className="card review-list">
              {g.items.map((i) => {
                const tag = resultTag(i);
                const played = i.home_score !== null && i.away_score !== null;
                return (
                  <li key={i.fixture_id} className="review-row">
                    <div className="review-match">
                      <span className="muted small">
                        <LocalTime iso={i.kickoff_at} fallbackTz={data.tz} format="time" fixed />
                      </span>
                      <Link href={`/fixtures/${i.fixture_id}`}>
                        {i.home_team.name}{" "}
                        <strong>{played ? `${i.home_score} : ${i.away_score}` : "vs"}</strong>{" "}
                        {i.away_team.name}
                      </Link>
                    </div>
                    <div className="review-calls small">
                      <span>
                        분석 <strong>{topLabel(i)}</strong>
                        {i.tier === "high" && <span className="muted"> · 확률 높음</span>}
                      </span>
                      {i.market_top_outcome && (
                        <span className="muted">
                          시장 1순위 {OUTCOME_LABEL[i.market_top_outcome]}
                        </span>
                      )}
                      <span className={`status ${tag.tone}`}>{tag.text}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
      <Disclaimer />
    </>
  );
}
