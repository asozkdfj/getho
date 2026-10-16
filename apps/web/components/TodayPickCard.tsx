import type { TodayPick } from "@edge/contracts";
import Link from "next/link";

import { OUTCOME_LABEL, pct } from "@/lib/format";
import { leagueLabel } from "@/lib/leagues";
import {
  closestCandidate,
  pickCautions,
  pickOutcomeText,
  pickReasons,
  backtestScope,
  periodText,
  pickStatusInfo,
  rateWithCi,
  thresholdText,
  voidReasonText,
} from "@/lib/picks";

import { LocalTime } from "./LocalTime";
import { ProbabilityBar } from "./ProbabilityBar";

/** Today's Pick: one frozen, published decision per day (or an honest "no pick"). */
export function TodayPickCard({ pick, tz }: { pick: TodayPick | null; tz: string }) {
  if (pick === null) {
    return (
      <section className="card pick-card" aria-labelledby="pick-title">
        <h2 id="pick-title" className="pick-title">
          오늘의 픽
        </h2>
        <p className="error small" style={{ margin: 0 }}>
          오늘의 픽 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.
        </p>
      </section>
    );
  }

  const info = pickStatusInfo(pick.status, pick.threshold);
  const f = pick.fixture;
  const closest = pick.status === "no_qualifying_match" ? closestCandidate(pick) : null;
  const hasPick = f && pick.outcome && pick.probability !== null && pick.probability !== undefined;

  return (
    <section
      className={`card pick-card${pick.status === "voided" ? " voided" : ""}`}
      aria-labelledby="pick-title"
    >
      <div className="pick-head">
        <h2 id="pick-title" className="pick-title">
          오늘의 픽 <span className="muted small">{pick.date} (한국 시간)</span>
        </h2>
        <span className={`status pick-status ${info.tone}`}>{info.label}</span>
      </div>
      {pick.is_demo && (
        <p className="demo-banner small">
          데모 데이터(합성 경기)로 만든 예시입니다. 실제 경기·실제 성과가 아니에요.
        </p>
      )}

      {hasPick ? (
        <>
          <div className="muted small pick-league">{leagueLabel(f.league)}</div>
          <div className="pick-match">
            <Link href={`/fixtures/${f.id}`} className="pick-teams">
              {f.home_team.name} <span className="muted">vs</span> {f.away_team.name}
            </Link>
            <span className="muted small">
              <LocalTime iso={f.kickoff_at} fallbackTz={tz} format="full" /> 킥오프
            </span>
          </div>
          <div className="pick-main">
            <div>
              <div className="muted small">분석이 가장 높게 본 결과</div>
              <div className="pick-outcome">
                {pickOutcomeText(pick.outcome!, f.home_team.name, f.away_team.name)}
              </div>
            </div>
            <div className="pick-prob">
              <div className="muted small">분석 확률</div>
              <div className="pick-prob-value">{pct(pick.probability, 0)}</div>
            </div>
          </div>
          {pick.probabilities && (
            <>
              <ProbabilityBar p={pick.probabilities} label="분석" />
              <p className="muted small" style={{ margin: "4px 0 0" }}>
                {OUTCOME_LABEL.HOME} {pct(pick.probabilities.home, 0)} · {OUTCOME_LABEL.DRAW}{" "}
                {pct(pick.probabilities.draw, 0)} · {OUTCOME_LABEL.AWAY}{" "}
                {pct(pick.probabilities.away, 0)} — 이 결과가 나오지 않을 가능성도{" "}
                {pct(1 - pick.probability!, 0)}입니다.
              </p>
            </>
          )}

          {pick.result?.event === "settled" && (
            <p className={`pick-result ${pick.result.hit ? "positive" : "negative"}`}>
              결과: {pick.result.actual_outcome && OUTCOME_LABEL[pick.result.actual_outcome]}
              {f.home_score !== null && ` (${f.home_score} : ${f.away_score})`} —{" "}
              {pick.result.hit ? "적중" : "빗나감"}
            </p>
          )}
          {pick.status === "voided" && (
            <p className="pick-result negative">
              무효: {voidReasonText(pick.result?.reason)}. {info.description}
            </p>
          )}

          <ul className="caveats">
            {pickCautions(pick).map((c) => (
              <li key={c}>⚠ {c}</li>
            ))}
          </ul>
          {pick.backtest && (
            <p className="small pick-backtest">
              같은 규칙의 과거 적중률{" "}
              <strong>{rateWithCi(pick.backtest.hit_rate, pick.backtest.hit_rate_ci)}</strong> —
              과거 성과가 앞으로를 보장하지 않아요.
            </p>
          )}

          <details className="pick-why">
            <summary>왜 이 경기인가요? 근거와 과거 기록 보기</summary>
            <ul className="pick-reasons">
              <li>
                오늘 경기 중 데이터 점검을 통과한 결과 가운데 분석 확률이 가장 높았고, 기준(
                {pct(pick.threshold, 0)})을 넘었어요.
              </li>
              {pickReasons(pick).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            {pick.backtest && (
              <p className="small">
                과거 기록: 같은 규칙({thresholdText(pick.backtest.threshold)})을{" "}
                {periodText(pick.backtest.period)}의 {backtestScope(pick.backtest.leagues)}에
                적용하면 {pick.backtest.match_days}일 중 {pick.backtest.days_with_pick}일에 픽이
                나왔고, 적중률 {rateWithCi(pick.backtest.hit_rate, pick.backtest.hit_rate_ci)}, 평균
                분석 확률 {pct(pick.backtest.mean_pick_probability, 0)}였어요.{" "}
                <Link href="/performance#daily">규칙 백테스트 자세히</Link>
              </p>
            )}
          </details>
          <p className="muted small pick-meta">
            모델 {pick.model?.version ?? "–"} · 데이터 기준{" "}
            {pick.input_data_as_of ? (
              <LocalTime iso={pick.input_data_as_of} fallbackTz={tz} />
            ) : (
              "–"
            )}{" "}
            · 선정 {pick.published_at ? <LocalTime iso={pick.published_at} fallbackTz={tz} /> : "–"}
            {pick.revision && pick.revision > 1 && ` · 교체 픽(${pick.revision}번째)`} ·{" "}
            <Link href={`/fixtures/${f.id}`}>경기 자세히</Link> · <Link href="/picks">지난 픽</Link>
          </p>
        </>
      ) : (
        <>
          <p style={{ margin: "6px 0" }}>
            {pick.status === "no_qualifying_match" && pick.matches_in_scope === 0
              ? "오늘은 정확도가 검증된 리그의 경기가 없어요. 검증 전 리그에서는 픽을 고르지 않아요."
              : info.description}
          </p>
          {closest && (
            <p className="muted small" style={{ margin: "0 0 6px" }}>
              {closest}
            </p>
          )}
          {pick.status === "scheduled" && (
            <p className="muted small" style={{ margin: 0 }}>
              선정 시각: <LocalTime iso={pick.publish_at} fallbackTz={tz} />
            </p>
          )}
          <p className="muted small" style={{ margin: "6px 0 0" }}>
            <Link href="/picks">지난 픽 보기</Link> ·{" "}
            <Link href="/guide#pick">픽은 어떻게 고르나요?</Link>
          </p>
        </>
      )}
      <p className="pick-disclaimer small">{pick.disclaimer}</p>
    </section>
  );
}
