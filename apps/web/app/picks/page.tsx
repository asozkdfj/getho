import type { PickHistoryItem } from "@edge/contracts";
import type { Metadata } from "next";
import Link from "next/link";

import { fetchPickHistory } from "@/lib/api";
import { DEFAULT_TZ } from "@/lib/config";
import { OUTCOME_LABEL, pct } from "@/lib/format";
import { historySummaryText, pickOutcomeText, pickStatusInfo, voidReasonText } from "@/lib/picks";

import { LocalTime } from "@/components/LocalTime";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "지난 오늘의 픽" };

function ResultTag({ item, label }: { item: PickHistoryItem; label: string }) {
  if (item.status === "settled") {
    return (
      <span className={`status ${item.hit ? "positive" : "negative"}`}>
        {item.actual_outcome && OUTCOME_LABEL[item.actual_outcome]} · {item.hit ? "적중" : "빗나감"}
      </span>
    );
  }
  if (item.status === "voided") {
    return <span className="status negative">무효 · {voidReasonText(item.reason)}</span>;
  }
  if (item.status === "published") return <span className="status">경기 전</span>;
  return <span className="status">{label}</span>;
}

export default async function PickHistoryPage() {
  const history = await fetchPickHistory(90);
  const tz = DEFAULT_TZ;
  const s = history.summary;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>지난 오늘의 픽</h1>
          <p className="muted small" style={{ margin: 0 }}>
            매일 선정 시각에 고정된 기록입니다. 나중에 결과를 보고 고치지 않아요.
          </p>
        </div>
      </div>
      {history.is_demo && (
        <p className="demo-banner small">
          데모 데이터(합성 경기)의 기록입니다. 실제 성과로 해석하지 마세요.
        </p>
      )}

      <div className="stat-grid">
        <div className="stat">
          <div className="label">선정한 날</div>
          <div className="value">{s.published}</div>
        </div>
        <div className="stat">
          <div className="label">결과 나옴 · 대기 · 무효</div>
          <div className="value">
            {s.settled} · {s.pending} · {s.voided}
          </div>
        </div>
        <div className="stat">
          <div className="label">적중률</div>
          <div className="value">{pct(s.hit_rate, 0)}</div>
          {s.hit_rate_ci && (
            <div className="muted small">
              범위 {pct(s.hit_rate_ci[0], 0)}–{pct(s.hit_rate_ci[1], 0)} · 표본 {s.settled}개
            </div>
          )}
        </div>
        <div className="stat">
          <div className="label">선정 당시 평균 분석 확률</div>
          <div className="value">{pct(s.mean_probability, 0)}</div>
        </div>
      </div>
      <p className="small">{historySummaryText(history)}</p>
      <p className="muted small">
        평균 분석 확률과 실제 적중률이 비슷할수록 확률이 믿을 만하다는 뜻이에요. {history.note}
      </p>

      {history.items.length === 0 ? (
        <p className="card small">아직 기록이 없어요.</p>
      ) : (
        <ol className="history-list">
          {history.items.map((item) => {
            const info = pickStatusInfo(item.status, 0);
            const hasPick = item.home && item.away && item.outcome && item.fixture_id;
            return (
              <li key={item.pick_id} className="card history-item">
                <div className="fixture-meta">
                  <span>
                    {item.date}
                    {item.revision > 1 && " · 교체 픽"}
                    {item.recorded_before_kickoff === false && " · 경기 시작 후 기록(성과 제외)"}
                  </span>
                  <ResultTag item={item} label={info.label} />
                </div>
                {hasPick ? (
                  <>
                    <Link href={`/fixtures/${item.fixture_id}`} className="history-match">
                      {item.home} vs {item.away}
                    </Link>
                    <div className="history-pick">
                      <span>{pickOutcomeText(item.outcome!, item.home!, item.away!)}</span>
                      <strong>{pct(item.probability, 0)}</strong>
                    </div>
                    <div className="muted small">
                      {item.kickoff_at && <LocalTime iso={item.kickoff_at} fallbackTz={tz} />}
                      {item.model_version && ` · 모델 ${item.model_version}`}
                    </div>
                  </>
                ) : (
                  <p className="muted small" style={{ margin: "4px 0 0" }}>
                    {item.status === "no_qualifying_match"
                      ? "데이터 점검을 통과하면서 기준 확률을 넘는 경기가 없어 고르지 않았어요."
                      : info.description}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
      <p className="disclaimer">
        확률은 추정치이며 결과를 보장하지 않습니다. 적중률은 표본이 수백 개는 쌓여야 의미가 있어요.
        베팅을 권유하지 않습니다.
      </p>
    </>
  );
}
