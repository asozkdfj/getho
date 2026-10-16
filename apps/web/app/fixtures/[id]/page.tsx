import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Disclaimer } from "@/components/Disclaimer";
import { LeagueBadge } from "@/components/LeagueBadge";
import { LocalTime } from "@/components/LocalTime";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { SimulationPanel } from "@/components/SimulationPanel";
import { TeamNewsSection } from "@/components/TeamNewsSection";
import { ApiError, fetchFixture, fetchPrediction } from "@/lib/api";
import { plainSummary } from "@/lib/explain";
import { leagueLabel, leagueNote } from "@/lib/leagues";
import { DEFAULT_TZ } from "@/lib/config";
import { OUTCOME_LABEL, odds, pct, signedPct, signedPoints, statusLabel, tone } from "@/lib/format";
import { qualityWarnings } from "@/lib/picks";
import { TERM, TERM_HELP } from "@/lib/terms";

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
  const warnings = qualityWarnings(prediction?.quality, fixture.status);
  const summary = prediction
    ? plainSummary(
        prediction,
        fixture.home_team.name,
        fixture.away_team.name,
        fixture.league.verified,
      )
    : null;

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
          <p className="small" style={{ margin: "0 0 2px" }}>
            <Link href={`/leagues/${fixture.league.id}`}>{leagueLabel(fixture.league)}</Link>{" "}
            <LeagueBadge league={fixture.league} />
          </p>
          <p className="muted small" style={{ margin: 0 }}>
            {fixture.season} · {fixture.round ? `${fixture.round}라운드 · ` : ""}
            <LocalTime iso={fixture.kickoff_at} fallbackTz={tz} format="full" /> ·{" "}
            {statusLabel(fixture.status)}
            {finished && ` · 결과 ${fixture.home_score} : ${fixture.away_score}`}
          </p>
        </div>
      </div>

      {prediction && summary ? (
        <>
          <section className="card summary-card" aria-label="한눈에 보기">
            <h2 style={{ marginTop: 0 }}>한눈에 보기</h2>
            <p>{summary.mostLikely}</p>
            <p>{summary.comparison}</p>
            {summary.ev && <p className="small">{summary.ev}</p>}
            {(summary.cautions.length > 0 || warnings.length > 0) && (
              <ul className="caveats">
                {warnings.length > 0 && (
                  <li>
                    ⚠ 데이터 점검을 통과하지 못한 항목이 있어 오늘의 픽 후보에서 빠져요:{" "}
                    {warnings.join(", ")}
                  </li>
                )}
                {summary.cautions.map((c) => (
                  <li key={c}>⚠ {c}</li>
                ))}
              </ul>
            )}
            {fixture.status !== "scheduled" && (
              <p className="small muted">경기 시작 전에 저장된 분석이에요.</p>
            )}
            <p className="small muted">
              용어가 낯설다면 <Link href="/guide">3분 가이드</Link>를 먼저 보세요.
            </p>
          </section>

          <section className="card stack" aria-label="확률 비교" style={{ marginTop: 12 }}>
            <ProbabilityBar p={prediction.probabilities} label="분석" />
            <ProbabilityBar p={prediction.fair_market_probabilities} label="시장 예상" />
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

          {fixture.status === "scheduled" && (
            <SimulationPanel
              fixtureId={fixture.id}
              home={fixture.home_team.name}
              away={fixture.away_team.name}
            />
          )}

          <h2>결과별 자세히 보기</h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">결과</th>
                  <HelpHeader term="odds" anchor="odds" />
                  <HelpHeader term="implied" anchor="odds" className="hide-narrow" />
                  <HelpHeader term="market" anchor="market" />
                  <HelpHeader term="model" anchor="model" />
                  <HelpHeader term="gap" anchor="gap" />
                  <HelpHeader term="ev" anchor="ev" />
                </tr>
              </thead>
              <tbody>
                {prediction.outcomes.map((o) => (
                  <tr key={o.outcome}>
                    <th scope="row">
                      {OUTCOME_LABEL[o.outcome]}
                      {o.exceeds_threshold && (
                        <span className="badge" title={TERM_HELP.flag}>
                          {TERM.flag}
                        </span>
                      )}
                    </th>
                    <td>{odds(o.decimal_odds)}</td>
                    <td className="muted hide-narrow">{pct(o.implied_probability)}</td>
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
            배당에 포함된 수수료 약 {pct(prediction.overround)}를 빼고 시장 예상을 계산했습니다.
            차이 = 분석 확률 − 시장 예상, 기대값 = 분석 확률 × 배당 − 1. &lsquo;{TERM.flag}&rsquo;
            표시는 차이와 기대값이 모두 {pct(prediction.value_threshold, 0)} 이상일 때만 붙는 참고
            표시이며 추천이 아닙니다.
          </p>
        </>
      ) : (
        <div className="card">
          <p style={{ margin: 0 }}>
            {fixture.league.type === "cup" || !fixture.league.predicted
              ? leagueNote(fixture.league)
              : finished || fixture.status === "live"
                ? "경기가 시작된 뒤에는 새로 분석하지 않아요. 이 경기는 시작 전에 저장된 분석이 없습니다."
                : "아직 이 경기의 분석이 없어요. 배당이 들어오면 자동으로 분석합니다."}
          </p>
        </div>
      )}

      {fixture.team_news && <TeamNewsSection news={fixture.team_news} tz={tz} />}

      {prediction && (
        <>
          <section className="card">
            <h3 style={{ marginTop: 0 }}>언제 기준의 분석인가요?</h3>
            <dl className="kv">
              <dt>분석에 쓴 데이터</dt>
              <dd>
                <LocalTime iso={prediction.input_data_as_of} fallbackTz={tz} format="full" />
                까지
              </dd>
              <dt>배당을 가져온 시각</dt>
              <dd>
                <LocalTime
                  iso={prediction.market_odds_snapshot.captured_at}
                  fallbackTz={tz}
                  format="full"
                />
              </dd>
              <dt>분석한 시각</dt>
              <dd>
                <LocalTime iso={prediction.created_at} fallbackTz={tz} format="full" />
              </dd>
              <dt>배당 출처</dt>
              <dd>{prediction.market_odds_snapshot.bookmaker}</dd>
              <dt>예상 골</dt>
              <dd>
                {fixture.home_team.short_name} {prediction.expected_goals.home.toFixed(1)} :{" "}
                {prediction.expected_goals.away.toFixed(1)} {fixture.away_team.short_name}
              </dd>
            </dl>
          </section>

          <details className="card tech">
            <summary>개발자용 모델 정보</summary>
            <dl className="kv" style={{ marginTop: 10 }}>
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
              <dt>Elo (홈/원정)</dt>
              <dd>
                {String(prediction.features.elo_home ?? "–")} /{" "}
                {String(prediction.features.elo_away ?? "–")}
              </dd>
              <dt>학습 경기 수</dt>
              <dd>{String(prediction.features.training_matches ?? "–")}</dd>
              <dt>출발점(prior)</dt>
              <dd>
                {String(prediction.features.prior_home ?? "–")} /{" "}
                {String(prediction.features.prior_away ?? "–")}
              </dd>
            </dl>
          </details>
        </>
      )}

      <h2>배당 변화 기록</h2>
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

function HelpHeader({
  term,
  anchor,
  className,
}: {
  term: keyof typeof TERM;
  anchor: string;
  className?: string;
}) {
  return (
    <th scope="col" title={TERM_HELP[term]} className={className}>
      {TERM[term]}
      <Link href={`/guide#${anchor}`} className="help" aria-label={`${TERM[term]} 설명`}>
        ?
      </Link>
    </th>
  );
}
