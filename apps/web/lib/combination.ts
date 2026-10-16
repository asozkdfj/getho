import {
  MAX_COMBINATION_LEGS,
  type Combination,
  type FixtureSummary,
  type Outcome,
} from "@edge/contracts";

import type { Ticket } from "./latestRequest";

export type Selections = Record<number, Outcome>;

export function isSelectable(f: FixtureSummary): boolean {
  return f.status === "scheduled" && f.prediction_id != null && pricedOdds(f) != null;
}

/** The odds a combination is priced on: the snapshot the stored prediction uses. */
export function pricedOdds(f: FixtureSummary) {
  return f.prediction_odds ?? null;
}

/** True when newer odds arrived after the prediction (the combination still uses the older ones). */
export function oddsUpdatedSincePrediction(f: FixtureSummary): boolean {
  const priced = pricedOdds(f);
  return priced != null && f.latest_odds != null && f.latest_odds.id !== priced.id;
}

/**
 * Toggle an outcome for a fixture.
 * - same outcome again -> deselect
 * - another outcome on a selected fixture -> switch
 * - new fixture -> add (ignored when full or blocked)
 */
export function toggleSelection(
  current: Selections,
  fixture: FixtureSummary,
  outcome: Outcome,
  all: FixtureSummary[],
): Selections {
  const next = { ...current };
  if (next[fixture.id] === outcome) {
    delete next[fixture.id];
    return next;
  }
  if (next[fixture.id] === undefined && blockReason(current, fixture, all) !== null) {
    return current;
  }
  next[fixture.id] = outcome;
  return next;
}

/** Why a fixture cannot be added right now (null = selectable). */
export function blockReason(
  current: Selections,
  fixture: FixtureSummary,
  all: FixtureSummary[],
): string | null {
  if (current[fixture.id] !== undefined) return null;
  if (!isSelectable(fixture)) return "예측 또는 배당이 아직 없습니다";
  const selectedIds = Object.keys(current).map(Number);
  if (selectedIds.length >= MAX_COMBINATION_LEGS) {
    return `최대 ${MAX_COMBINATION_LEGS}경기까지 선택할 수 있습니다`;
  }
  const teams = new Set<number>();
  for (const f of all) {
    if (selectedIds.includes(f.id)) {
      teams.add(f.home_team.id);
      teams.add(f.away_team.id);
    }
  }
  if (teams.has(fixture.home_team.id) || teams.has(fixture.away_team.id)) {
    return "같은 팀이 포함된 경기는 함께 조합할 수 없습니다";
  }
  return null;
}

export function toRequest(selections: Selections) {
  return {
    selections: Object.entries(selections).map(([id, outcome]) => ({
      fixture_id: Number(id),
      outcome,
    })),
  };
}

/** Team-name search (case-insensitive, either side, full or short name). */
export function matchesTeam(f: FixtureSummary, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [f.home_team.name, f.home_team.short_name, f.away_team.name, f.away_team.short_name].some(
    (s) => s.toLowerCase().includes(needle),
  );
}

export interface Leg {
  fixture: FixtureSummary;
  outcome: Outcome;
}

/** The current selections in kickoff order (unknown fixture ids are dropped). */
export function selectedLegs(selections: Selections, all: FixtureSummary[]): Leg[] {
  return all
    .filter((f) => selections[f.id] !== undefined)
    .map((f) => ({ fixture: f, outcome: selections[f.id]! }));
}

/** Short text for a selected outcome, e.g. "Arsenal 승" or "ARS-CRY 무". */
export function legLabel(
  f: Pick<FixtureSummary, "home_team" | "away_team">,
  outcome: Outcome,
): string {
  if (outcome === "HOME") return `${f.home_team.name} 승`;
  if (outcome === "AWAY") return `${f.away_team.name} 승`;
  return `${f.home_team.short_name}-${f.away_team.short_name} 무`;
}

/** Number of selected fixtures per league id. */
export function selectedPerLeague(
  selections: Selections,
  all: FixtureSummary[],
): Map<number, number> {
  const counts = new Map<number, number>();
  for (const { fixture } of selectedLegs(selections, all)) {
    counts.set(fixture.league.id, (counts.get(fixture.league.id) ?? 0) + 1);
  }
  return counts;
}

export type AnalysisOutcome =
  | { kind: "result"; combination: Combination }
  | { kind: "error"; message: string }
  | { kind: "stale" }; // answer for a request the user has since replaced or cancelled

/** POST the selection; a stale answer (ticket no longer current) is never applied. */
export async function requestAnalysis(
  selections: Selections,
  ticket: Ticket,
  fetchImpl: typeof fetch = fetch,
): Promise<AnalysisOutcome> {
  try {
    const res = await fetchImpl("/api/combinations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toRequest(selections)),
      signal: ticket.signal,
    });
    const body = await res.json();
    if (!ticket.isCurrent()) return { kind: "stale" };
    if (!res.ok) {
      const message =
        typeof body?.detail === "string" ? body.detail : "분석 요청이 거부되었습니다.";
      return { kind: "error", message };
    }
    return { kind: "result", combination: body as Combination };
  } catch {
    if (!ticket.isCurrent()) return { kind: "stale" };
    return { kind: "error", message: "API에 연결할 수 없습니다. 잠시 후 다시 시도하세요." };
  }
}
