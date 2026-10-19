import type { LiveClv, Research, ResearchDay, ShadowProgress } from "@edge/contracts";
import type { Metadata } from "next";

import { fetchResearch, orNull } from "@/lib/api";
import { pct } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "연구" };

const f3 = (x: number | null | undefined) => (x == null ? "–" : x.toFixed(3));
const share = (x: number | null | undefined) => (x == null ? "–" : pct(x, 0));
const signed = (x: number | null | undefined) =>
  x == null ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)}%`;

/** Experiments so far (docs/MODEL_EVALUATION.md); static, updated with each result. */
const LEDGER: { name: string; status: "adopted" | "rejected" | "pending"; note: string }[] = [
  { name: "승격팀 사전값 (v0.2.0)", status: "adopted", note: "끄면 log loss +0.003(확정은 아님)" },
  { name: "파라미터 11개 조정", status: "rejected", note: "이미 거의 최적" },
  { name: "온도 보정", status: "rejected", note: "개선이 잡음 수준" },
  { name: "피로·휴식", status: "rejected", note: "오히려 악화" },
  { name: "순위·동기", status: "rejected", note: "기준(0.002)에 한참 미달" },
  { name: "무승부 비율 보정", status: "rejected", note: "기준에 한참 미달" },
  { name: "배당과 섞기 (0.25 + 0.75)", status: "rejected", note: "시장 단독보다 나쁨" },
  { name: "언더/오버·핸디캡 표시", status: "rejected", note: "표시 조건 미달" },
  { name: "강팀 확률 보정", status: "pending", note: "2026-27 확인 실험, 2027-06 채점" },
  { name: "선발 명단 변수", status: "pending", note: "+0.2%, 큰 표본으로 재측정 필요" },
  { name: "병행 기록 (shadow-v1)", status: "pending", note: "10/20~12/14, 12월 중순 채점" },
  { name: "CLV (과거·실시간)", status: "pending", note: "모델에 시장이 모르는 정보가 있는가" },
];

const STATUS_LABEL = { adopted: "채택", rejected: "미채택", pending: "진행 중" } as const;

function CollectionSection({ c }: { c: Research["collection"] }) {
  const problems = [
    ...c.days_without_decision.map((d) => `${d} 픽 결정 없음`),
    ...c.days_with_failed_runs.map((d) => `${d} 실패한 수집`),
    ...c.days_with_long_gaps.map((d) => `${d} 긴 공백`),
    ...c.days_with_shadow_errors.map((d) => `${d} 병행 기록 오류`),
  ];
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>수집 상태 (최근 {c.days.length}일)</h2>
      <p className={problems.length ? "negative" : "positive"}>
        {problems.length ? `확인할 것 ${problems.length}건: ${problems.join(", ")}` : "문제 없음"}
      </p>
      <p className="small muted">
        결정 시점 예측 {share(c.prediction_share)} · 배당 {share(c.odds_share)} · 결장 정보{" "}
        {share(c.absences_known_share)} · 예정 수집 간격 {Math.round(c.expected_interval_minutes)}분
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">날짜</th>
              <th scope="col">픽 결정</th>
              <th scope="col">수집 성공/실패</th>
              <th scope="col">최장 공백</th>
              <th scope="col">경기 (예측·배당)</th>
              <th scope="col">병행 기록</th>
            </tr>
          </thead>
          <tbody>
            {c.days.map((d: ResearchDay) => (
              <tr key={d.day}>
                <td>{d.day}</td>
                <td>
                  {d.decided ? (
                    `+${d.minutes_after_publish_hour ?? "?"}분`
                  ) : (
                    <span className="negative">없음</span>
                  )}
                </td>
                <td>
                  {d.runs_success}/
                  {d.runs_failed > 0 ? <span className="negative">{d.runs_failed}</span> : 0}
                </td>
                <td>{d.longest_gap_hours == null ? "–" : `${d.longest_gap_hours}시간`}</td>
                <td>
                  {d.fixtures_at_decision} ({d.with_prediction}·{d.with_odds})
                </td>
                <td>
                  {d.shadow_error ? <span className="negative">오류</span> : d.shadow_recorded}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ShadowSection({ s }: { s: ShadowProgress }) {
  const progress = Math.min(1, s.settled / s.min_settled);
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>병행 기록 ({s.protocol})</h2>
      <p>
        {s.window_start} ~ {s.window_end} · 결과 확정 <strong>{s.settled.toLocaleString()}</strong>{" "}
        / 최소 {s.min_settled.toLocaleString()}경기 ({pct(progress, 0)}) · 대기 {s.pending} · 경기
        안 열림 {s.not_played}
      </p>
      <p className="small muted">
        기록 {s.recorded.toLocaleString()}행, 기록된 날 {s.days_with_records}일
        {s.decision_delay_median_minutes != null &&
          ` · 결정 시각 중앙값 9시 +${Math.round(s.decision_delay_median_minutes)}분`}
        {s.no_decision_days.length > 0 && ` · 결정 없는 날 ${s.no_decision_days.join(", ")}`}
      </p>
      {Object.keys(s.excluded).length > 0 && (
        <p className="small muted">
          제외:{" "}
          {Object.entries(s.excluded)
            .map(([k, v]) => `${k} ${v}`)
            .join(", ")}
        </p>
      )}
      {s.status === "final" ? (
        <p>
          채점 완료. 자세한 결과는 <code>edge shadow-report</code>로 확인하세요.
        </p>
      ) : (
        <p className="small">
          평가 기간이 끝나기 전에는 성적을 보여 주지 않아요. 중간 결과를 보고 규칙을 바꾸지 않기
          위해서예요.
        </p>
      )}
    </section>
  );
}

function ClvSection({ c }: { c: LiveClv }) {
  const [lo, hi] = c.b_model_ci;
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>실시간 CLV (오전 9시 판단 → 킥오프 직전 배당)</h2>
      {c.analysed === 0 ? (
        <p className="small">
          아직 계산할 경기가 없어요. 병행 기록이 쌓이고 경기가 시작되면 채워집니다.
          {Object.keys(c.counts).length > 0 &&
            ` (${Object.entries(c.counts)
              .map(([k, v]) => `${k} ${v}`)
              .join(", ")})`}
        </p>
      ) : (
        <>
          <p>
            배당이 모델 쪽으로 움직인 정도 b = <strong>{f3(c.b_model)}</strong>{" "}
            <span className="muted small">
              (95% 범위 {f3(lo)} ~ {f3(hi)}, {c.analysed}경기 · {c.days}일)
            </span>{" "}
            —{" "}
            {c.signal === "positive" ? (
              <span className="positive">시장이 모르는 정보 신호</span>
            ) : (
              <span className="muted">아직 신호 없음</span>
            )}
          </p>
          <p className="small muted">
            모델 쪽으로 움직인 비율 {share(c.share_moves_toward_model)} · 평균 변동{" "}
            {c.mean_abs_move == null ? "–" : pct(c.mean_abs_move, 1)} · 종가 스냅샷 중앙값 킥오프{" "}
            {c.closing_minutes_before_kickoff_median == null
              ? "–"
              : `${Math.round(c.closing_minutes_before_kickoff_median)}분 전`}{" "}
            · 평균 쪽 되돌림 몫 {f3(c.b_base)}
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">&lsquo;차이 큼&rsquo; 기준</th>
                  <th scope="col">해당 결과</th>
                  <th scope="col">평균 CLV</th>
                  <th scope="col">CLV 양수 비율</th>
                </tr>
              </thead>
              <tbody>
                {c.large_gap.map((g) => (
                  <tr key={g.threshold}>
                    <td>{pct(g.threshold, 0)}p 이상</td>
                    <td>{g.flags}</td>
                    <td>{signed(g.mean_clv)}</td>
                    <td>{share(g.share_positive)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p className="small muted" style={{ marginBottom: 0 }}>
        배당만 봅니다(경기 결과를 읽지 않음). b는 평균 쪽으로 되돌아가는 몫을 뺀 값이고, 0이면 정보
        없음, 1이면 종가가 모델과 같아진다는 뜻이에요. 모니터링용이며 모델·픽을 바꾸지 않아요.
      </p>
    </section>
  );
}

export default async function ResearchPage() {
  const data = await orNull(fetchResearch());
  return (
    <>
      <div className="page-head">
        <div>
          <h1>연구</h1>
          <p className="muted small" style={{ margin: 0 }}>
            수집 상태와 진행 중인 실험을 한곳에서 봐요. 운영 모델과 픽은 여기서 바뀌지 않아요.
          </p>
        </div>
      </div>
      {data == null ? (
        <p className="card">연구 데이터를 불러오지 못했어요. API 상태를 확인해 주세요.</p>
      ) : (
        <>
          {data.is_demo && (
            <p className="card small">
              데모 데이터예요. 실데이터 모드에서 의미 있는 값이 나옵니다.
            </p>
          )}
          <CollectionSection c={data.collection} />
          <ShadowSection s={data.shadow} />
          <ClvSection c={data.live_clv} />
        </>
      )}
      <section className="card">
        <h2 style={{ marginTop: 0 }}>실험 기록</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">실험</th>
                <th scope="col">결과</th>
                <th scope="col">메모</th>
              </tr>
            </thead>
            <tbody>
              {LEDGER.map((e) => (
                <tr key={e.name}>
                  <td>{e.name}</td>
                  <td className={e.status === "adopted" ? "positive" : undefined}>
                    {STATUS_LABEL[e.status]}
                  </td>
                  <td className="small">{e.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginBottom: 0 }}>
          자세한 수치는 &lsquo;모델 성과&rsquo;와 저장소의 docs/MODEL_EVALUATION.md에 있어요.
        </p>
      </section>
    </>
  );
}
