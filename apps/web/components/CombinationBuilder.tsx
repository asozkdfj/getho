"use client";

import {
  MAX_COMBINATION_LEGS,
  MIN_COMBINATION_LEGS,
  OUTCOMES,
  type Combination,
  type FixtureSummary,
} from "@edge/contracts";
import { useState } from "react";

import { blockReason, toggleSelection, toRequest, type Selections } from "@/lib/combination";
import {
  OUTCOME_LABEL,
  OUTCOME_SHORT,
  odds,
  pct,
  signedPct,
  signedPoints,
  tone,
} from "@/lib/format";

import { LocalTime } from "./LocalTime";

const ODDS_KEY = { HOME: "odds_home", DRAW: "odds_draw", AWAY: "odds_away" } as const;
const PROB_KEY = { HOME: "home", DRAW: "draw", AWAY: "away" } as const;

export function CombinationBuilder({ fixtures, tz }: { fixtures: FixtureSummary[]; tz: string }) {
  const [selections, setSelections] = useState<Selections>({});
  const [result, setResult] = useState<Combination | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const count = Object.keys(selections).length;
  const ready = count >= MIN_COMBINATION_LEGS && count <= MAX_COMBINATION_LEGS;

  function pick(f: FixtureSummary, outcome: (typeof OUTCOMES)[number]) {
    setSelections((s) => toggleSelection(s, f, outcome, fixtures));
    setResult(null);
    setError(null);
  }

  async function analyze() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/combinations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toRequest(selections)),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(typeof body?.detail === "string" ? body.detail : "분석 요청이 거부되었습니다.");
        setResult(null);
      } else {
        setResult(body as Combination);
      }
    } catch {
      setError("API에 연결할 수 없습니다. 잠시 후 다시 시도하세요.");
    } finally {
      setLoading(false);
    }
  }

  if (fixtures.length === 0) {
    return (
      <p className="card">분석 가능한 예정 경기가 없습니다 (예측과 배당이 있는 경기만 표시).</p>
    );
  }

  return (
    <>
      <div className="stack">
        {fixtures.map((f) => {
          const reason = blockReason(selections, f, fixtures);
          return (
            <div key={f.id} className="card pick-row">
              <div className="fixture-meta">
                <LocalTime iso={f.kickoff_at} fallbackTz={tz} />
                {reason && selections[f.id] === undefined && (
                  <span className="small">{reason}</span>
                )}
              </div>
              <div className="teams">
                {f.home_team.name} <span className="muted">vs</span> {f.away_team.name}
              </div>
              <div className="pick-buttons" role="group" aria-label="결과 선택">
                {OUTCOMES.map((o) => (
                  <button
                    key={o}
                    type="button"
                    aria-pressed={selections[f.id] === o}
                    disabled={reason !== null && selections[f.id] === undefined}
                    onClick={() => pick(f, o)}
                  >
                    <span>
                      {OUTCOME_SHORT[o]} · {odds(f.latest_odds?.[ODDS_KEY[o]])}
                    </span>
                    <small>모델 {pct(f.model_probabilities?.[PROB_KEY[o]], 0)}</small>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="sticky-bar">
        <span>
          선택 <strong>{count}</strong> / {MAX_COMBINATION_LEGS}
          {count < MIN_COMBINATION_LEGS && (
            <span className="muted small"> · 최소 {MIN_COMBINATION_LEGS}경기</span>
          )}
        </span>
        <span style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="btn secondary"
            onClick={() => {
              setSelections({});
              setResult(null);
              setError(null);
            }}
            disabled={count === 0}
          >
            초기화
          </button>
          <button type="button" className="btn" disabled={!ready || loading} onClick={analyze}>
            {loading ? "계산 중…" : "조합 분석"}
          </button>
        </span>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {result && <CombinationResult result={result} tz={tz} />}
    </>
  );
}

function CombinationResult({ result, tz }: { result: Combination; tz: string }) {
  return (
    <section aria-live="polite">
      <h2>분석 결과</h2>
      <div className="stat-grid">
        <div className="stat">
          <div className="label">모델 조합 확률</div>
          <div className="value">{pct(result.model_probability, 2)}</div>
        </div>
        <div className="stat">
          <div className="label">시장 공정 조합 확률</div>
          <div className="value">{pct(result.fair_market_probability, 2)}</div>
        </div>
        <div className="stat">
          <div className="label">조합 배당</div>
          <div className="value">{odds(result.combined_odds)}</div>
        </div>
        <div className="stat">
          <div className="label">Edge</div>
          <div className={`value ${tone(result.edge, 0.001)}`}>{signedPoints(result.edge, 2)}</div>
        </div>
        <div className="stat">
          <div className="label">EV (1 단위당)</div>
          <div className={`value ${tone(result.expected_value)}`}>
            {signedPct(result.expected_value)}
          </div>
        </div>
      </div>

      <h3>선택 경기</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">경기</th>
              <th scope="col">선택</th>
              <th scope="col">배당</th>
              <th scope="col">모델</th>
              <th scope="col">시장 공정</th>
              <th scope="col">EV</th>
            </tr>
          </thead>
          <tbody>
            {result.legs.map((leg) => (
              <tr key={leg.fixture_id}>
                <td>
                  {leg.home_team.short_name} vs {leg.away_team.short_name}
                  <div className="muted small">
                    배당 <LocalTime iso={leg.odds_captured_at} fallbackTz={tz} /> 기준
                  </div>
                </td>
                <td>{OUTCOME_LABEL[leg.outcome]}</td>
                <td>{odds(leg.decimal_odds)}</td>
                <td>{pct(leg.model_probability)}</td>
                <td>{pct(leg.fair_probability)}</td>
                <td className={tone(leg.expected_value)}>{signedPct(leg.expected_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="notes">
        <li>
          계산 방식: <code>{result.method}</code> (근사치)
        </li>
        {result.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
        <li>
          조합 배당의 내재확률 {pct(result.implied_probability, 2)} — 공정확률과의 차이는 누적된
          북메이커 마진입니다.
        </li>
      </ul>
    </section>
  );
}
