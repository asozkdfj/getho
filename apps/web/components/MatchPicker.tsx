"use client";

import { OUTCOMES, type FixtureSummary, type Outcome } from "@edge/contracts";
import { useMemo, useState } from "react";

import { OUTCOME_SHORT, pct, statusLabel } from "@/lib/format";
import { defaultScope, inScope, pickerGroups, type PickerScope } from "@/lib/personalPicks";

import { LeagueMark } from "./LeagueMark";
import { LocalTime } from "./LocalTime";

const PROB_KEY = { HOME: "home", DRAW: "draw", AWAY: "away" } as const;
const SCOPES: { key: PickerScope; label: string }[] = [
  { key: "featured", label: "주요 리그" },
  { key: "verified", label: "검증 리그" },
  { key: "all", label: "전체" },
];
/** Leagues open at first; a search or a click opens the rest. */
const OPEN_GROUPS = 3;

export interface MatchChoice {
  fixtureId: number;
  selection: Outcome;
}

/**
 * Pick a match and a result in one tap: search by team or league, narrow by
 * league scope, and press 홈승 / 무 / 원정승 on the match row (the model's
 * probability is shown on each button when there is a prediction).
 */
export function MatchPicker({
  fixtures,
  tz,
  value,
  onChange,
}: {
  fixtures: FixtureSummary[];
  tz: string;
  value: MatchChoice | null;
  onChange: (choice: MatchChoice) => void;
}) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<PickerScope>(() => defaultScope(fixtures));
  const [flipped, setFlipped] = useState<Set<number>>(new Set());
  const searching = query.trim() !== "";
  const groups = useMemo(
    () => pickerGroups(fixtures, query, searching ? "all" : scope),
    [fixtures, query, scope, searching],
  );
  const counts = useMemo(
    () =>
      Object.fromEntries(
        SCOPES.map((s) => [s.key, fixtures.filter((f) => inScope(f, s.key)).length]),
      ) as Record<PickerScope, number>,
    [fixtures],
  );

  const isOpen = (id: number, index: number) =>
    (searching || index < OPEN_GROUPS || groups.length === 1) !== flipped.has(id);
  const flip = (id: number) =>
    setFlipped((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="match-picker">
      <div className="picker-tools">
        <input
          type="search"
          className="picker-search"
          placeholder="팀이나 리그 이름으로 찾기"
          aria-label="팀이나 리그 이름으로 경기 찾기"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            // a league folded before must not hide its search results
            setFlipped(new Set());
          }}
        />
        {!searching && (
          <div className="league-chips" role="group" aria-label="리그 범위">
            {SCOPES.map((s) => (
              <button
                key={s.key}
                type="button"
                className="chip"
                aria-pressed={scope === s.key}
                disabled={counts[s.key] === 0}
                onClick={() => setScope(s.key)}
              >
                {s.label} <span className="chip-count">{counts[s.key]}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {groups.length === 0 && (
        <p className="muted small" style={{ margin: "8px 0" }}>
          {searching ? `'${query.trim()}'에 맞는 경기가 없어요.` : "이 범위에는 경기가 없어요."}
        </p>
      )}

      {groups.map((g, index) => {
        const open = isOpen(g.league.id, index);
        return (
          <section key={g.league.id} className="picker-group">
            <h3 className="picker-group-head">
              <button
                type="button"
                aria-expanded={open}
                aria-controls={`mp-league-${g.league.id}`}
                onClick={() => flip(g.league.id)}
              >
                <span className="picker-caret" aria-hidden="true">
                  {open ? "▾" : "▸"}
                </span>
                <LeagueMark league={g.league} />
                <span className="picker-group-name">
                  <span className="muted">{g.league.country_ko} · </span>
                  {g.league.name}
                </span>
                <span className="muted small nowrap">{g.fixtures.length}경기</span>
              </button>
            </h3>
            {open && (
              <div className="picker-rows mp-rows" id={`mp-league-${g.league.id}`}>
                {g.fixtures.map((f) => {
                  const chosen = value?.fixtureId === f.id;
                  const probs = f.model_probabilities;
                  return (
                    <div key={f.id} className={`pick-row${chosen ? " chosen" : ""}`}>
                      <div className="pick-info">
                        <span className="muted small">
                          <LocalTime iso={f.kickoff_at} fallbackTz={tz} format="time" fixed />
                          {f.status !== "scheduled" && ` · ${statusLabel(f.status)}`}
                        </span>
                        <span className="teams">
                          {f.home_team.name} <span className="muted">vs</span> {f.away_team.name}
                        </span>
                      </div>
                      <div
                        className="pick-buttons"
                        role="group"
                        aria-label={`${f.home_team.name} 대 ${f.away_team.name} 선택`}
                      >
                        {OUTCOMES.map((o) => (
                          <button
                            key={o}
                            type="button"
                            aria-pressed={chosen && value?.selection === o}
                            onClick={() => onChange({ fixtureId: f.id, selection: o })}
                          >
                            <strong>{OUTCOME_SHORT[o]}</strong>
                            <small>{probs ? pct(probs[PROB_KEY[o]], 0) : "–"}</small>
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
    </div>
  );
}
