"use client";

import type { FixtureSummary } from "@edge/contracts";

import type { Selections } from "@/lib/combination";
import { OUTCOME_LABEL, pct } from "@/lib/format";
import { topWindowCombos } from "@/lib/windowCombos";

const WINDOW_HOURS = 8;

function when(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: tz,
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

/** Top 5 three-match combinations whose kickoffs fit in an 8-hour window. */
export function WindowCombos({
  fixtures,
  tz,
  demo = false,
  onApply,
}: {
  fixtures: FixtureSummary[];
  tz: string;
  demo?: boolean;
  onApply: (selections: Selections) => void;
}) {
  const combos = topWindowCombos(fixtures, { windowHours: WINDOW_HOURS, demo });
  return (
    <section className="card window-combos" aria-label="시간대 추천 조합">
      <h2>같은 시간대 3경기 추천 조합 TOP 5</h2>
      <p className="muted small" style={{ margin: "0 0 10px" }}>
        킥오프가 {WINDOW_HOURS}시간 안에 모두 있는 3경기 중, 각 경기의 가장 높은 결과가 모두 맞을
        확률(분석)이 높은 순서예요. {demo ? "데모 경기" : "정확도를 검증한 리그"}만 쓰고, 같은 팀은
        두 번 넣지 않아요.
      </p>
      {combos.length === 0 ? (
        <p className="small">8시간 안에 묶을 수 있는 경기가 3개보다 적어요.</p>
      ) : (
        <ol className="window-combo-list">
          {combos.map((c, i) => (
            <li key={c.legs.map((l) => l.fixture.id).join("-")} className="window-combo">
              <div className="window-combo-head">
                <span className={`window-rank rank-${i + 1}`}>{i + 1}단계</span>
                <div className="window-prob">
                  <strong>{pct(c.probability, 1)}</strong>
                  <span className="muted small"> 모두 맞을 확률(분석)</span>
                </div>
                <div className="window-market small muted">
                  시장 기준 {c.marketProbability == null ? "–" : pct(c.marketProbability, 1)}
                </div>
              </div>
              <div className="window-bar" aria-hidden="true">
                <span style={{ width: `${Math.min(100, c.probability * 100 * 2)}%` }} />
              </div>
              <p className="window-span small muted">
                {when(c.firstKickoff, tz)} ~ {when(c.lastKickoff, tz)} · 첫 경기부터{" "}
                {c.spanHours.toFixed(1)}시간
              </p>
              <ul className="window-legs">
                {c.legs.map((l) => (
                  <li key={l.fixture.id}>
                    <span className="window-leg-time small muted">
                      {when(l.fixture.kickoff_at, tz)}
                    </span>
                    <span className="window-leg-match">
                      {l.fixture.home_team.name} <span className="muted">vs</span>{" "}
                      {l.fixture.away_team.name}
                      <span className="muted small"> · {l.fixture.league.name}</span>
                    </span>
                    <span className={`window-leg-pick pick-${l.outcome.toLowerCase()}`}>
                      {OUTCOME_LABEL[l.outcome]} {pct(l.probability, 0)}
                    </span>
                  </li>
                ))}
              </ul>
              <button type="button" className="btn secondary" onClick={() => onApply(c.selections)}>
                이 조합 자세히 분석
              </button>
            </li>
          ))}
        </ol>
      )}
      <p className="small muted" style={{ marginBottom: 0 }}>
        경기끼리 서로 영향을 주지 않는다고 보고 곱한 근사치예요. 과거 3시즌(2023-26, 554일) 하루
        상위 3경기 조합은 분석이 평균 27%라고 했을 때 실제로 33% 맞았어요. 결과를 보장하지 않습니다.
      </p>
    </section>
  );
}
