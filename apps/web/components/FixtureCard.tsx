import type { FixtureSummary } from "@edge/contracts";
import Link from "next/link";

import { OUTCOME_SHORT, pct, signedPoints, statusLabel, tone } from "@/lib/format";
import { OUTCOMES } from "@edge/contracts";

import { LocalTime } from "./LocalTime";

const KEY = { HOME: "home", DRAW: "draw", AWAY: "away" } as const;

export function FixtureCard({ fixture, tz }: { fixture: FixtureSummary; tz: string }) {
  const model = fixture.model_probabilities;
  const fair = fixture.fair_market_probabilities;
  const finished = fixture.status === "finished";
  return (
    <Link href={`/fixtures/${fixture.id}`} className="card fixture-card">
      <div className="fixture-meta">
        <LocalTime iso={fixture.kickoff_at} fallbackTz={tz} format="time" />
        <span className="fixture-tags">
          {fixture.lineups_announced && fixture.status === "scheduled" && (
            <span className="status lineup-out">명단 발표</span>
          )}
          <span className={`status status-${fixture.status}`}>{statusLabel(fixture.status)}</span>
        </span>
      </div>
      <div className="fixture-teams">
        <span className="team">{fixture.home_team.name}</span>
        <span className="score">
          {finished ? `${fixture.home_score} : ${fixture.away_score}` : "vs"}
        </span>
        <span className="team away">{fixture.away_team.name}</span>
      </div>
      {model && fair ? (
        <div className="mini-grid" aria-label="분석 확률과 시장 예상 비교">
          {OUTCOMES.map((o) => {
            const m = model[KEY[o]];
            const f = fair[KEY[o]];
            return (
              <div key={o} className="mini-cell">
                <span className="mini-head">{OUTCOME_SHORT[o]}</span>
                <span className="mini-model">{pct(m, 0)}</span>
                <span className="mini-fair">시장 {pct(f, 0)}</span>
                <span className={`mini-edge ${tone(m - f)}`}>{signedPoints(m - f)}</span>
              </div>
            );
          })}
        </div>
      ) : fair && !finished ? (
        <>
          <div className="mini-grid" aria-label="시장 예상">
            {OUTCOMES.map((o) => (
              <div key={o} className="mini-cell">
                <span className="mini-head">{OUTCOME_SHORT[o]}</span>
                <span className="mini-model">{pct(fair[KEY[o]], 0)}</span>
                <span className="mini-fair">시장 예상</span>
              </div>
            ))}
          </div>
          <p className="muted small" style={{ margin: "6px 0 0" }}>
            {fixture.league.type === "cup"
              ? "컵 대회라 분석 확률 없이 시장 예상만 보여 드려요"
              : "분석 준비 중 · 지금은 시장 예상만 있어요"}
          </p>
        </>
      ) : (
        <p className="muted small">{finished ? "경기 종료" : "배당 수집 전"}</p>
      )}
    </Link>
  );
}
