import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Disclaimer } from "@/components/Disclaimer";
import { LocalTime } from "@/components/LocalTime";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { ApiError, fetchFixture, fetchPrediction } from "@/lib/api";
import { DEFAULT_TZ } from "@/lib/config";
import { OUTCOME_LABEL, odds, pct, signedPct, signedPoints, statusLabel, tone } from "@/lib/format";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

async function load(idParam: string) {
  const id = Number(idParam);
  if (!Number.isInteger(id) || id <= 0) notFound();
  try {
    const [fixture, prediction] = await Promise.all([fetchFixture(id), fetchPrediction(id)]);
    return { fixture, prediction };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { fixture } = await load((await params).id);
  return { title: `${fixture.home_team.name} vs ${fixture.away_team.name}` };
}

export default async function FixturePage({ params }: { params: Params }) {
  const { fixture, prediction } = await load((await params).id);
  const tz = DEFAULT_TZ;
  const finished = fixture.status === "finished";

  return (
    <>
      <p className="small">
        <Link href="/">← 경기 목록</Link>
      </p>
      <div className="page-head">
        <div>
          <h1>
            {fixture.home_team.name} <span className="muted">vs</span> {fixture.away_team.name}
          </h1>
          <p className="muted small" style={{ margin: 0 }}>
            {fixture.season} · {fixture.round}라운드 ·{" "}
            <LocalTime iso={fixture.kickoff_at} fallbackTz={tz} format="full" /> ·{" "}
            {statusLabel(fixture.status)}
            {finished && ` · 결과 ${fixture.home_score} : ${fixture.away_score}`}
          </p>
        </div>
      </div>

      {prediction ? (
        <>
          <section className="card stack" aria-label="확률 비교">
            <ProbabilityBar p={prediction.probabilities} label="모델" />
            <ProbabilityBar p={prediction.fair_market_probabilities} label="시장(공정)" />
            <div className="legend">
              <span>
                <i className="dot" style={{ background: "var(--home)" }} />홈
              </span>
              <span>
                <i className="dot" style={{ background: "var(--draw)" }} />무
              </span>
              <span>
                <i className="dot" style={{ background: "var(--away)" }} />
                원정
              </span>
            </div>
          </section>

          <h2>1X2 분석</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">결과</th>
                  <th scope="col">배당</th>
                  <th scope="col">내재확률</th>
                  <th scope="col">시장 공정확률</th>
                  <th scope="col">모델 확률</th>
                  <th scope="col">Edge</th>
                  <th scope="col">EV</th>
                </tr>
              </thead>
              <tbody>
                {prediction.outcomes.map((o) => (
                  <tr key={o.outcome}>
                    <th scope="row">
                      {OUTCOME_LABEL[o.outcome]}
                      {o.exceeds_threshold && (
                        <span className="badge" title="Edge와 EV가 모두 기준치 이상인 참고 신호">
                          기준 초과
                        </span>
                      )}
                    </th>
                    <td>{odds(o.decimal_odds)}</td>
                    <td className="muted">{pct(o.implied_probability)}</td>
                    <td>{pct(o.fair_probability)}</td>
                    <td>
                      <strong>{pct(o.model_probability)}</strong>
                    </td>
                    <td className={tone(o.edge)}>{signedPoints(o.edge)}</td>
                    <td className={tone(o.expected_value)}>{signedPct(o.expected_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            북메이커 마진(overround) {pct(prediction.overround)} 제거 ({prediction.devig_method}).
            Edge = 모델 − 공정확률, EV = 모델확률 × 배당 − 1. &lsquo;기준 초과&rsquo;는 Edge와 EV가
            모두 {pct(prediction.value_threshold, 0)} 이상인 참고 신호일 뿐 추천이 아닙니다.
          </p>

          <div className="grid-2">
            <section className="card">
              <h3 style={{ marginTop: 0 }}>데이터 기준 시각</h3>
              <dl className="kv">
                <dt>입력 데이터 as-of</dt>
                <dd>
                  <LocalTime iso={prediction.input_data_as_of} fallbackTz={tz} format="full" />
                </dd>
                <dt>배당 수집 시각</dt>
                <dd>
                  <LocalTime
                    iso={prediction.market_odds_snapshot.captured_at}
                    fallbackTz={tz}
                    format="full"
                  />
                </dd>
                <dt>예측 생성 시각</dt>
                <dd>
                  <LocalTime iso={prediction.created_at} fallbackTz={tz} format="full" />
                </dd>
                <dt>북메이커</dt>
                <dd>{prediction.market_odds_snapshot.bookmaker}</dd>
              </dl>
            </section>
            <section className="card">
              <h3 style={{ marginTop: 0 }}>모델 정보</h3>
              <dl className="kv">
                <dt>모델</dt>
                <dd>
                  {prediction.model.name} v{prediction.model.version}
                </dd>
                <dt>git sha</dt>
                <dd>
                  <code>{prediction.model.git_sha}</code>
                </dd>
                <dt>feature set</dt>
                <dd>{prediction.model.feature_set}</dd>
                <dt>calibration</dt>
                <dd>{prediction.model.calibration}</dd>
                <dt>기대 득점</dt>
                <dd>
                  {prediction.expected_goals.home.toFixed(2)} :{" "}
                  {prediction.expected_goals.away.toFixed(2)}
                </dd>
                <dt>Elo (홈/원정)</dt>
                <dd>
                  {String(prediction.features.elo_home ?? "–")} /{" "}
                  {String(prediction.features.elo_away ?? "–")}
                </dd>
                <dt>학습 경기 수</dt>
                <dd>{String(prediction.features.training_matches ?? "–")}</dd>
              </dl>
            </section>
          </div>
        </>
      ) : (
        <div className="card">
          <p style={{ margin: 0 }}>
            {finished || fixture.status === "live"
              ? "경기 시작 이후에는 새 예측을 만들지 않습니다. 이 경기에는 저장된 사전 예측이 없습니다."
              : "아직 이 경기의 모델 예측이 없습니다. 시장 배당이 수집되면 예측이 생성됩니다."}
          </p>
        </div>
      )}

      <h2>배당 변화 (append-only 스냅샷)</h2>
      {fixture.odds_history.length === 0 ? (
        <p className="muted">수집된 배당이 없습니다.</p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">수집 시각</th>
                <th scope="col">홈</th>
                <th scope="col">무</th>
                <th scope="col">원정</th>
              </tr>
            </thead>
            <tbody>
              {fixture.odds_history.map((o) => (
                <tr key={o.id}>
                  <td>
                    <LocalTime iso={o.captured_at} fallbackTz={tz} />
                  </td>
                  <td>{odds(o.odds_home)}</td>
                  <td>{odds(o.odds_draw)}</td>
                  <td>{odds(o.odds_away)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Disclaimer />
    </>
  );
}
