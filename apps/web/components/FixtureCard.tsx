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
        <span className={`status status-${fixture.status}`}>{statusLabel(fixture.status)}</span>
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
      ) : (
        <p className="muted small">
          {finished ? "경기 종료" : fair ? "분석 준비 중" : "배당 수집 전"}
        </p>
      )}
    </Link>
  );
}
