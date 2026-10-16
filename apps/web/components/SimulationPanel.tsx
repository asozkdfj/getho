"use client";

import type { Simulation } from "@edge/contracts";
import { useEffect, useRef, useState } from "react";

import { OUTCOME_LABEL, pct } from "@/lib/format";
import {
  DEFAULT_RUNS,
  agreementText,
  newSeed,
  replayResultText,
  timeline,
  visibleGoals,
} from "@/lib/simulation";

const KEYS = [
  ["HOME", "home"],
  ["DRAW", "draw"],
  ["AWAY", "away"],
] as const;
const REPLAY_MS = 3000; // whole replay plays in ~3 seconds

/** Replays the match many times from the analysis (no new information is added). */
export function SimulationPanel({
  fixtureId,
  home,
  away,
}: {
  fixtureId: number;
  home: string;
  away: string;
}) {
  const [sim, setSim] = useState<Simulation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [minute, setMinute] = useState(90);
  const panelRef = useRef<HTMLDivElement>(null);

  async function run(seed?: number) {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ runs: String(DEFAULT_RUNS) });
      if (seed !== undefined) q.set("seed", String(seed));
      const res = await fetch(`/api/simulation/${fixtureId}?${q.toString()}`);
      const body = await res.json();
      if (!res.ok) {
        setError(typeof body?.detail === "string" ? body.detail : "시뮬레이션을 하지 못했어요.");
        return;
      }
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      setMinute(reduce ? 90 : 0);
      setSim(body as Simulation);
    } catch {
      setError("서버에 연결할 수 없어요. 잠시 후 다시 시도하세요.");
    } finally {
      setLoading(false);
    }
  }

  // Step through the single replay minute by minute (skipped with reduced motion).
  useEffect(() => {
    if (!sim) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      const m = Math.min(90, Math.round(((Date.now() - started) / REPLAY_MS) * 90));
      setMinute(m);
      if (m >= 90) window.clearInterval(timer);
    }, 50);
    panelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return () => window.clearInterval(timer);
  }, [sim]);

  if (!sim) {
    return (
      <section className="card simulation" aria-labelledby="sim-title">
        <h2 id="sim-title" style={{ marginTop: 0 }}>
          경기 시뮬레이션
        </h2>
        <p className="small" style={{ marginTop: 0 }}>
          분석이 계산한 기대 득점으로 이 경기를 {DEFAULT_RUNS.toLocaleString()}번 다시 치러 봐요.
          어떤 스코어가 자주 나오는지, 골이 몇 개쯤 나오는지 볼 수 있어요.
        </p>
        <button type="button" className="btn" onClick={() => run()} disabled={loading}>
          {loading ? "시뮬레이션 중…" : `${DEFAULT_RUNS.toLocaleString()}번 시뮬레이션`}
        </button>
        {error && (
          <p className="error small" role="alert">
            {error}
          </p>
        )}
      </section>
    );
  }

  const items = timeline(sim.replay);
  const shown = visibleGoals(items, minute);
  const last = shown.at(-1);
  const maxTotal = Math.max(...sim.total_goals.map(([, s]) => s));
  const maxScore = Math.max(...sim.top_scores.map((s) => s.share));

  return (
    <section className="card simulation" aria-labelledby="sim-title" ref={panelRef}>
      <div className="sim-head">
        <h2 id="sim-title" style={{ margin: 0 }}>
          경기 시뮬레이션
        </h2>
        <button
          type="button"
          className="btn secondary"
          onClick={() => run(newSeed())}
          disabled={loading}
        >
          {loading ? "계산 중…" : "다시 돌리기"}
        </button>
      </div>

      <h3>한 경기 다시보기</h3>
      <div className="replay" aria-live="polite">
        <div className="replay-score">
          <span>{home}</span>
          <strong>{last ? last.score : "0 : 0"}</strong>
          <span>{away}</span>
        </div>
        <div className="replay-track" aria-hidden>
          <div className="replay-progress" style={{ width: `${(minute / 90) * 100}%` }} />
          {shown.map((g, i) => (
            <span
              key={`${g.minute}-${i}`}
              className={`replay-goal ${g.side}`}
              style={{ left: `${(g.minute / 90) * 100}%` }}
              title={`${g.minute}분`}
            />
          ))}
        </div>
        <p className="muted small" style={{ margin: "4px 0 0" }}>
          {minute < 90 ? `${minute}분` : `경기 종료 · ${replayResultText(sim.replay, home, away)}`}
          {shown.length > 0 &&
            ` · 골: ${shown.map((g) => `${g.minute}' ${g.side === "home" ? home : away}`).join(", ")}`}
        </p>
      </div>

      <h3>{sim.runs.toLocaleString()}번 다시 치르면</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">결과</th>
              <th scope="col">시뮬레이션</th>
              <th scope="col">분석 확률</th>
            </tr>
          </thead>
          <tbody>
            {KEYS.map(([label, key]) => (
              <tr key={key}>
                <td>{OUTCOME_LABEL[label]}</td>
                <td>
                  <strong>{pct(sim.outcome_share[key], 1)}</strong>
                </td>
                <td className="muted">{pct(sim.model_probabilities[key], 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small">{agreementText(sim)}</p>

      <div className="grid-2">
        <div>
          <h3>자주 나온 스코어</h3>
          <ul className="sim-bars">
            {sim.top_scores.slice(0, 6).map((s) => (
              <li key={`${s.home}-${s.away}`}>
                <span className="sim-label">
                  {s.home} : {s.away}
                </span>
                <span className="sim-bar">
                  <span style={{ width: `${(s.share / maxScore) * 100}%` }} />
                </span>
                <span className="sim-value">{pct(s.share, 1)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>두 팀 골 합계</h3>
          <ul className="sim-bars">
            {sim.total_goals.map(([label, share]) => (
              <li key={label}>
                <span className="sim-label">{label}골</span>
                <span className="sim-bar">
                  <span style={{ width: `${(share / maxTotal) * 100}%` }} />
                </span>
                <span className="sim-value">{pct(share, 1)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="stat-grid" style={{ marginTop: 10 }}>
        <div className="stat">
          <div className="label">3골 이상 (2.5 초과)</div>
          <div className="value">{pct(sim.over["2.5"], 0)}</div>
        </div>
        <div className="stat">
          <div className="label">양 팀 모두 득점</div>
          <div className="value">{pct(sim.both_teams_score, 0)}</div>
        </div>
        <div className="stat">
          <div className="label">{home} 무실점</div>
          <div className="value">{pct(sim.home_clean_sheet, 0)}</div>
        </div>
        <div className="stat">
          <div className="label">{away} 무실점</div>
          <div className="value">{pct(sim.away_clean_sheet, 0)}</div>
        </div>
      </div>

      <p className="muted small" style={{ marginBottom: 0 }}>
        {sim.note} 기대 득점 {home} {sim.expected_goals.home.toFixed(2)} :{" "}
        {sim.expected_goals.away.toFixed(2)} {away} · 시드 {sim.seed}
      </p>
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
