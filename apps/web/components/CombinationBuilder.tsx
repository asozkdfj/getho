"use client";

import {
  MAX_COMBINATION_LEGS,
  MIN_COMBINATION_LEGS,
  OUTCOMES,
  type Combination,
  type FixtureSummary,
} from "@edge/contracts";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  blockReason,
  legLabel,
  matchesTeam,
  oddsUpdatedSincePrediction,
  pricedOdds,
  requestAnalysis,
  selectedLegs,
  selectedPerLeague,
  toggleSelection,
  type Selections,
} from "@/lib/combination";
import { OUTCOME_SHORT, odds, pct, signedPct, signedPoints, tone } from "@/lib/format";
import { LatestRequest } from "@/lib/latestRequest";
import { groupByLeague, leagueLabel } from "@/lib/leagues";

import { LeagueBadge } from "./LeagueBadge";
import { LeagueMark } from "./LeagueMark";
import { LocalTime } from "./LocalTime";

const ODDS_KEY = { HOME: "odds_home", DRAW: "odds_draw", AWAY: "odds_away" } as const;
const PROB_KEY = { HOME: "home", DRAW: "draw", AWAY: "away" } as const;
function scrollBehavior(): ScrollBehavior {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

/** With many leagues, only the first few groups start open. */
const OPEN_GROUPS = 4;

export function CombinationBuilder({
  fixtures,
  tz,
  order = [],
}: {
  fixtures: FixtureSummary[];
  tz: string;
  /** League ids in display order (featured ranking first). */
  order?: number[];
}) {
  const [selections, setSelections] = useState<Selections>({});
  const [result, setResult] = useState<Combination | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [league, setLeague] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [toggled, setToggled] = useState<Set<number>>(new Set());
  const count = Object.keys(selections).length;
  const ready = count >= MIN_COMBINATION_LEGS && count <= MAX_COMBINATION_LEGS;
  const resultRef = useRef<HTMLElement>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);

  const groups = useMemo(() => groupByLeague(fixtures, order), [fixtures, order]);
  const legs = selectedLegs(selections, fixtures);
  const perLeague = selectedPerLeague(selections, fixtures);
  const searching = query.trim() !== "";
  const visible = groups
    .filter((g) => league === null || g.league.id === league)
    .map((g) => ({ ...g, fixtures: g.fixtures.filter((f) => matchesTeam(f, query)) }))
    .filter((g) => g.fixtures.length > 0);

  // Bring the outcome into view as soon as it arrives (the list can be long).
  useEffect(() => {
    const target = result ? resultRef.current : error ? errorRef.current : null;
    if (!target) return;
    target.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
    target.focus({ preventScroll: true });
  }, [result, error]);

  // Changing the selection voids (and aborts) a running analysis so a late
  // answer for an old combination is never shown (QA-01).
  const [request] = useState(() => new LatestRequest());

  function cancelRequest() {
    request.cancel();
    setLoading(false);
  }

  function update(next: Selections) {
    cancelRequest();
    setSelections(next);
    setResult(null);
    setError(null);
  }

  function pick(f: FixtureSummary, outcome: (typeof OUTCOMES)[number]) {
    update(toggleSelection(selections, f, outcome, fixtures));
  }

  function remove(id: number) {
    const next = { ...selections };
    delete next[id];
    update(next);
  }

  // A group is open by default when it is among the first few, holds a
  // selection, or the list is narrowed (one league or a search); a click flips it.
  function isOpen(id: number, index: number) {
    const byDefault =
      index < OPEN_GROUPS || league !== null || searching || (perLeague.get(id) ?? 0) > 0;
    return toggled.has(id) ? !byDefault : byDefault;
  }

  function flip(id: number) {
    setToggled((t) => {
      const next = new Set(t);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function analyze() {
    const ticket = request.start();
    setLoading(true);
    setError(null);
    const outcome = await requestAnalysis(selections, ticket);
    if (outcome.kind === "stale") return;
    setLoading(false);
    if (outcome.kind === "error") {
      setError(outcome.message);
      setResult(null);
    } else {
      setResult(outcome.combination);
    }
  }

  if (fixtures.length === 0) {
    return (
      <p className="card">분석 가능한 예정 경기가 없습니다 (예측과 배당이 있는 경기만 표시).</p>
    );
  }

  return (
    <>
      <div className="picker-tools">
        <input
          type="search"
          className="picker-search"
          placeholder="팀 이름으로 찾기"
          aria-label="팀 이름으로 경기 찾기"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="league-chips" role="group" aria-label="리그 선택">
          <button
            type="button"
            className="chip"
            aria-pressed={league === null}
            onClick={() => setLeague(null)}
          >
            전체 리그 <span className="chip-count">{fixtures.length}</span>
          </button>
          {groups.map((g) => (
            <button
              key={g.league.id}
              type="button"
              className="chip"
              aria-pressed={league === g.league.id}
              onClick={() => setLeague(league === g.league.id ? null : g.league.id)}
            >
              <LeagueMark league={g.league} size={16} />
              {g.league.name}
              <span className="chip-count">{g.fixtures.length}</span>
              {(perLeague.get(g.league.id) ?? 0) > 0 && (
                <span className="chip-picked" aria-label={`${perLeague.get(g.league.id)}개 선택됨`}>
                  {perLeague.get(g.league.id)}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {visible.length === 0 && (
        <p className="card small">
          {searching ? `'${query.trim()}'이(가) 들어간 팀의 경기가 없어요.` : "경기가 없어요."}
        </p>
      )}

      {visible.map((g, index) => {
        const open = isOpen(g.league.id, index);
        const picked = perLeague.get(g.league.id) ?? 0;
        return (
          <section key={g.league.id} className="picker-group">
            <h2 className="picker-group-head">
              <button
                type="button"
                aria-expanded={open}
                aria-controls={`league-${g.league.id}`}
                onClick={() => flip(g.league.id)}
              >
                <span className="picker-caret" aria-hidden="true">
                  {open ? "▾" : "▸"}
                </span>
                <LeagueMark league={g.league} />
                <span className="picker-group-name" title={leagueLabel(g.league)}>
                  <span className="muted hide-narrow">{g.league.country_ko} · </span>
                  {g.league.name}
                </span>
                <span className="muted small nowrap">{g.fixtures.length}경기</span>
                {picked > 0 && <span className="chip-picked nowrap">{picked}개 선택</span>}
              </button>
              <LeagueBadge league={g.league} />
            </h2>
            {open && (
              <div className="card picker-rows" id={`league-${g.league.id}`}>
                {g.fixtures.map((f) => {
                  const reason = blockReason(selections, f, fixtures);
                  const chosen = selections[f.id];
                  return (
                    <div key={f.id} className={`pick-row${chosen ? " chosen" : ""}`}>
                      <div className="pick-info">
                        <span className="muted small">
                          <LocalTime iso={f.kickoff_at} fallbackTz={tz} />
                        </span>
                        <span className="teams">
                          {f.home_team.name} <span className="muted">vs</span> {f.away_team.name}
                        </span>
                        {reason && chosen === undefined && (
                          <span className="small muted">{reason}</span>
                        )}
                        {oddsUpdatedSincePrediction(f) && (
                          <span className="small muted">
                            배당이 새로 들어왔어요. 분석이 갱신될 때까지{" "}
                            <LocalTime iso={pricedOdds(f)!.captured_at} fallbackTz={tz} /> 배당으로
                            계산해요.
                          </span>
                        )}
                      </div>
                      <div
                        className="pick-buttons"
                        role="group"
                        aria-label={`${f.home_team.name} vs ${f.away_team.name} 결과 선택`}
                      >
                        {OUTCOMES.map((o) => (
                          <button
                            key={o}
                            type="button"
                            aria-pressed={chosen === o}
                            disabled={reason !== null && chosen === undefined}
                            onClick={() => pick(f, o)}
                          >
                            <small>{OUTCOME_SHORT[o]}</small>
                            <strong>{odds(pricedOdds(f)?.[ODDS_KEY[o]])}</strong>
                            <small>분석 {pct(f.model_probabilities?.[PROB_KEY[o]], 0)}</small>
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        );
      })}

      <div className="sticky-bar">
        {legs.length > 0 && (
          <ul className="tray" aria-label="고른 결과">
            {legs.map(({ fixture, outcome }) => (
              <li key={fixture.id}>
                <button
                  type="button"
                  className="tray-item"
                  onClick={() => remove(fixture.id)}
                  aria-label={`${legLabel(fixture, outcome)} 선택 해제`}
                  title={`${fixture.home_team.name} vs ${fixture.away_team.name}`}
                >
                  {legLabel(fixture, outcome)} <span aria-hidden="true">✕</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="sticky-row">
          {result ? (
            <button
              type="button"
              className="sticky-summary"
              onClick={() =>
                resultRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: "start" })
              }
            >
              <span className="hide-narrow">모두 맞을 확률 </span>
              <strong>분석 {pct(result.model_probability, 1)}</strong>
              <span className="muted"> · 시장 {pct(result.fair_market_probability, 1)}</span>
              <span className="small nowrap"> 결과 ↓</span>
            </button>
          ) : (
            <span className="sticky-status">
              선택 <strong>{count}</strong> / {MAX_COMBINATION_LEGS}
              {count < MIN_COMBINATION_LEGS && (
                <span className="muted small"> · {MIN_COMBINATION_LEGS - count}경기 더</span>
              )}
            </span>
          )}
          <span className="sticky-actions">
            <button
              type="button"
              className="btn secondary"
              onClick={() => update({})}
              disabled={count === 0}
            >
              초기화
            </button>
            <button type="button" className="btn" disabled={!ready || loading} onClick={analyze}>
              {loading ? "계산 중…" : "조합 분석"}
            </button>
          </span>
        </div>
      </div>

      {error && (
        <p className="error" role="alert" ref={errorRef} tabIndex={-1}>
          {error}
        </p>
      )}
      {result && <CombinationResult result={result} tz={tz} ref={resultRef} />}
    </>
  );
}

function CombinationResult({
  result,
  tz,
  ref,
}: {
  result: Combination;
  tz: string;
  ref: React.Ref<HTMLElement>;
}) {
  return (
    <section aria-live="polite" ref={ref} tabIndex={-1} className="combination-result">
      <h2>분석 결과</h2>
      <div className="stat-grid">
        <div className="stat">
          <div className="label">모두 맞을 확률 (분석)</div>
          <div className="value">{pct(result.model_probability, 2)}</div>
        </div>
        <div className="stat">
          <div className="label">모두 맞을 확률 (시장 예상)</div>
          <div className="value">{pct(result.fair_market_probability, 2)}</div>
        </div>
        <div className="stat">
          <div className="label">조합 배당</div>
          <div className="value">{odds(result.combined_odds)}</div>
        </div>
        <div className="stat">
          <div className="label">차이</div>
          <div className={`value ${tone(result.edge, 0.001)}`}>{signedPoints(result.edge, 2)}</div>
        </div>
        <div className="stat">
          <div className="label">기대값</div>
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
              <th scope="col">선택한 결과</th>
              <th scope="col">배당</th>
              <th scope="col">분석</th>
              <th scope="col">시장 예상</th>
              <th scope="col">기대값</th>
            </tr>
          </thead>
          <tbody>
            {result.legs.map((leg) => (
              <tr key={leg.fixture_id}>
                <td className="leg-cell">
                  <strong>{legLabel(leg, leg.outcome)}</strong>
                  <div className="small">
                    {leg.home_team.name} vs {leg.away_team.name}
                  </div>
                  <div className="muted small hide-narrow">
                    배당 <LocalTime iso={leg.odds_captured_at} fallbackTz={tz} /> 기준
                  </div>
                </td>
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
          계산 방식: 각 경기 확률을 곱한 근사치 (<code>{result.method}</code>)
        </li>
        {result.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
        <li>
          조합 배당을 그대로 확률로 바꾸면 {pct(result.implied_probability, 2)}입니다. 시장 예상과의
          차이는 경기마다 붙은 수수료가 쌓인 것입니다.
        </li>
      </ul>
    </section>
  );
}
