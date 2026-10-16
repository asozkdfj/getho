import type { DailyPickBacktestRow, ModelMetric } from "@edge/contracts";
import type { Metadata } from "next";
import Link from "next/link";

import { CalibrationChart } from "@/components/CalibrationChart";
import { fetchPerformance } from "@/lib/api";
import { pct } from "@/lib/format";
import { backtestTimingText, modelName, periodText, rateWithCi } from "@/lib/picks";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "모델 성과" };

const f3 = (x: number) => x.toFixed(3);
const f4 = (x: number) => x.toFixed(4);

function MetricTable({ rows, production }: { rows: ModelMetric[]; production: string }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th scope="col">모델</th>
            <th scope="col">경기 수</th>
            <th scope="col">Log loss ↓ (95% 범위)</th>
            <th scope="col">Brier ↓</th>
            <th scope="col">RPS ↓</th>
            <th scope="col">최다 확률 적중</th>
            <th scope="col">ECE ↓</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.name} className={m.name === "production" ? "row-highlight" : undefined}>
              <td>
                {modelName(m.name)}
                {m.name === "production" && <span className="badge">v{production}</span>}
              </td>
              <td>{m.n}</td>
              <td>
                {f4(m.log_loss)}{" "}
                <span className="muted small">
                  ({f3(m.log_loss_ci[0]!)}–{f3(m.log_loss_ci[1]!)})
                </span>
              </td>
              <td>{f4(m.brier)}</td>
              <td>{f4(m.rps)}</td>
              <td>{pct(m.accuracy, 1)}</td>
              <td>{f3(m.ece)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PickRuleTable({ rows }: { rows: DailyPickBacktestRow[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th scope="col">기준 확률</th>
            <th scope="col">픽 나온 날 / 경기 있는 날</th>
            <th scope="col">적중</th>
            <th scope="col">적중률 (95% 범위)</th>
            <th scope="col">평균 분석 확률</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.min_probability}>
              <td>{r.min_probability === 0 ? "기준 없음" : pct(r.min_probability, 0)}</td>
              <td>
                {r.days_with_pick} / {r.match_days}{" "}
                <span className="muted small">
                  ({pct(r.days_with_pick / Math.max(r.match_days, 1), 0)})
                </span>
              </td>
              <td>{r.hits}</td>
              <td>{rateWithCi(r.hit_rate, r.hit_rate_ci)}</td>
              <td>{pct(r.mean_pick_probability, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function PerformancePage() {
  const perf = await fetchPerformance();
  const ev = perf.evaluation;
  const evLeagues = ev?.leagues ?? [];
  const pickLeagues = ev?.daily_picks_leagues ?? [];
  const timing = ev?.daily_picks_timing ?? [];
  const live = perf.live;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>모델 성과</h1>
          <p className="muted small" style={{ margin: 0 }}>
            측정한 숫자만 보여 줍니다. 측정하지 못한 항목은 &lsquo;측정 안 됨&rsquo;으로 표시해요.
          </p>
        </div>
      </div>

      {!ev ? (
        <p className="card">
          아직 저장된 백테스트 결과가 없어요. <code>make seed</code>가 커밋된 실데이터 백테스트
          보고서를 불러옵니다.
        </p>
      ) : (
        <>
          <section className="card summary-card">
            <h2 style={{ marginTop: 0 }}>한눈에 보기</h2>
            <p>
              과거 실제 경기로, 매주 그 시점까지의 데이터만 써서 다시 학습하며 다음 경기를 예측해
              봤어요(미래 정보 사용 없음). 자세한 평가는 EPL {ev.n_matches.toLocaleString()}경기(
              {ev.seasons[0]}~{ev.seasons[ev.seasons.length - 1]})로 했고
              {evLeagues.length > 1 &&
                `, 같은 모델을 ${evLeagues.length}개 리그에 적용해 리그별로도 채점했어요`}
              .
            </p>
            <p>
              최종 평가는 학습·튜닝에 쓰지 않은 <strong>{periodText(ev.split.test)}</strong>{" "}
              경기로만 했어요. 숫자가 낮을수록 좋은 지표(↓)는 기본 비율 모델보다 확실히 낮아야
              의미가 있어요.
            </p>
            <p className="small muted" style={{ marginBottom: 0 }}>
              데이터: {ev.dataset} ({ev.license ?? "라이선스 정보 없음"}) · 시장(배당) 비교:{" "}
              {ev.has_odds ? "포함" : "측정 안 됨 — 공개 데이터에 과거 배당이 없음"}
            </p>
          </section>

          <h2>EPL 시험 구간 성적 ({periodText(ev.split.test)})</h2>
          <MetricTable rows={ev.test} production={ev.production_version} />
          <p className="muted small">
            Log loss·Brier·RPS: 확률이 실제 결과와 얼마나 가까운지(낮을수록 좋음). 최다 확률 적중:
            가장 높게 본 결과가 실제로 나온 비율. ECE: 말한 확률과 실제 비율의 평균 차이(낮을수록
            좋음).
          </p>

          <h2>확률은 믿을 만한가요? (EPL 보정 그래프)</h2>
          <div className="grid-2">
            <CalibrationChart bins={ev.calibration} />
            <div className="small">
              <p>
                분석이 &ldquo;60%&rdquo;라고 한 경기들에서 실제로 60% 정도 그 결과가 나왔다면 점이
                점선 위에 놓여요. 점선보다 아래면 분석이 자신감이 과했다는 뜻이에요.
              </p>
              <p className="muted">점 크기는 경기 수. 경기 수가 적은 구간은 우연의 영향이 커요.</p>
            </div>
          </div>

          <h2>EPL 시즌별 (현재 모델)</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">시즌</th>
                  <th scope="col">경기 수</th>
                  <th scope="col">Log loss</th>
                  <th scope="col">Brier</th>
                  <th scope="col">최다 확률 적중</th>
                </tr>
              </thead>
              <tbody>
                {ev.test_per_season.map((s) => (
                  <tr key={s.season}>
                    <td>{s.season}</td>
                    <td>{s.n}</td>
                    <td>{f4(s.log_loss)}</td>
                    <td>{f4(s.brier)}</td>
                    <td>{pct(s.accuracy, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {evLeagues.length > 0 && (
            <>
              <h2 id="leagues">리그별 결과 (같은 모델, {periodText(ev.split.test)})</h2>
              <p className="small">
                리그마다 그 리그의 결과로만 학습한 <strong>같은 모델</strong>을, 아무 정보 없이 평균
                비율만 쓴 기본 모델과 비교했어요. 좋아진 폭의 95% 범위가 0보다 크고 시험 경기가
                300개 이상이면 <strong>정확도 검증됨</strong>으로 표시합니다. 이 표에 없는 리그는
                정확도를 측정하지 않았어요.
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">리그</th>
                      <th scope="col">시험 경기</th>
                      <th scope="col">Log loss ↓</th>
                      <th scope="col">기본 모델</th>
                      <th scope="col">Elo만</th>
                      <th scope="col">좋아진 폭 (95% 범위)</th>
                      <th scope="col">최다 확률 적중</th>
                      <th scope="col">검증</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evLeagues.map((lg) => (
                      <tr key={lg.code}>
                        <td>
                          {lg.name}
                          <span className="muted small"> {lg.country}</span>
                        </td>
                        <td>{lg.test_matches}</td>
                        <td>{f4(lg.production.log_loss)}</td>
                        <td>{f4(lg.base_rate.log_loss)}</td>
                        <td>{lg.elo_only ? f4(lg.elo_only.log_loss) : "–"}</td>
                        <td>
                          +{f3(lg.gain_vs_base_rate[0]!)}{" "}
                          <span className="muted small">
                            ({f3(lg.gain_vs_base_rate[1]!)}–{f3(lg.gain_vs_base_rate[2]!)})
                          </span>
                        </td>
                        <td>{pct(lg.production.accuracy, 1)}</td>
                        <td className={lg.verified ? "positive" : "muted"}>
                          {lg.verified ? "검증됨" : "미달"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">
                2부 리그(Championship, 2. Bundesliga)는 기본 모델보다는 좋지만 Elo만 쓴 모델과
                비슷하거나 약간 못했어요. 리그별로 따로 맞추지 않은 같은 모델의 결과입니다.
              </p>
            </>
          )}

          <h2 id="daily">오늘의 픽 규칙 백테스트</h2>
          <p className="small">
            하루(한국 시간)에 경기 중 분석 확률이 가장 높은 결과 하나를 고르되, 기준 확률에 못
            미치면 그날은 고르지 않는 규칙을 시험 구간에 적용한 결과예요. 기준이 높을수록 적중률은
            오르지만 픽이 나오는 날은 줄어요.
            {pickLeagues.length > 0 &&
              ` 서비스처럼 검증된 ${pickLeagues.length}개 리그의 경기를 모두 모아 계산했어요.`}
          </p>
          {timing.length > 0 && (
            <>
              <h3>서비스 방식: 오전 9시에 선정</h3>
              <p className="small muted">{backtestTimingText(9)}</p>
              <PickRuleTable rows={timing} />
            </>
          )}
          <h3>{timing.length > 0 ? "참고: 하루 전체 경기를 후보로 본 계산" : "규칙 백테스트"}</h3>
          <p className="small muted">{backtestTimingText(null)}</p>
          <PickRuleTable rows={ev.daily_picks} />

          <h2>EPL 검증 구간 ({periodText(ev.split.validation)})</h2>
          <MetricTable rows={ev.validation} production={ev.production_version} />

          {Object.keys(ev.promotion_decisions).length > 0 && (
            <details className="tech">
              <summary>모델 교체 판단 기록</summary>
              <ul>
                {Object.entries(ev.promotion_decisions).map(([k, reasons]) => (
                  <li key={k}>
                    {k === "promotion" ? "튜닝 후보" : "튜닝 후보 + 온도 보정"}: 교체 안 함 —{" "}
                    {reasons.join("; ")}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      <h2>실시간 기록 (저장된 예측 vs 실제 결과)</h2>
      {live.is_demo && (
        <p className="demo-banner small">
          현재 데이터는 합성 데모입니다. 아래 숫자는 정확도 근거가 아니에요.
        </p>
      )}
      {live.n_matches === 0 || !live.model ? (
        <p className="card small">
          측정 안 됨 — 결과가 나온 경기의 저장된 예측이 아직 없어요. 경기가 끝나면 자동으로
          쌓입니다.
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">비교 대상</th>
                <th scope="col">경기 수</th>
                <th scope="col">Log loss ↓ (95% 범위)</th>
                <th scope="col">Brier ↓</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["분석(모델)", live.model],
                  ["시장(배당)", live.market],
                ] as const
              ).map(([label, side]) => (
                <tr key={label}>
                  <td>{label}</td>
                  <td>{live.n_matches}</td>
                  <td>
                    {side ? (
                      <>
                        {f4(side.log_loss)}{" "}
                        <span className="muted small">
                          ({f3(side.log_loss_ci[0]!)}–{f3(side.log_loss_ci[1]!)})
                        </span>
                      </>
                    ) : (
                      "측정 안 됨"
                    )}
                  </td>
                  <td>{side ? f4(side.brier) : "측정 안 됨"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        {perf.note} 표본이 수백 경기 이상 쌓이기 전에는 어느 쪽이 더 정확한지 결론을 내리지 않아요.
      </p>
      <p className="small">
        <Link href="/picks">지난 오늘의 픽 →</Link> · <Link href="/methodology">방법론 →</Link>
      </p>
    </>
  );
}
