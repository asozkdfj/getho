import type { FixtureSummary, Outcome } from "@edge/contracts";

import { isSelectable, type Selections } from "./combination";
import { topOutcome } from "./confidence";

/** Candidates searched exhaustively (the most likely outcomes first). */
const POOL = 16;

export interface SuggestedLeg {
  fixture: FixtureSummary;
  outcome: Outcome;
  probability: number;
}

export interface Suggestion {
  legs: SuggestedLeg[];
  selections: Selections;
  /** Product of the legs' model probabilities (independence approximation). */
  probability: number;
}

function combinations<T>(items: T[], size: number): T[][] {
  if (size === 0) return [[]];
  const out: T[][] = [];
  items.forEach((item, i) => {
    for (const rest of combinations(items.slice(i + 1), size - 1)) out.push([item, ...rest]);
  });
  return out;
}

function shareTeam(legs: SuggestedLeg[]): boolean {
  const teams = new Set<number>();
  for (const { fixture } of legs) {
    for (const id of [fixture.home_team.id, fixture.away_team.id]) {
      if (teams.has(id)) return true;
      teams.add(id);
    }
  }
  return false;
}

/**
 * The combination of ``size`` different matches whose most likely outcomes are
 * all right with the highest model probability. Only selectable matches of
 * verified leagues (the ones the probabilities were checked on; every league on
 * demo data) take part, and no team may appear twice. Ties: earlier kickoff,
 * then lower fixture id.
 */
export function suggestCombination(
  fixtures: FixtureSummary[],
  size: number,
  demo = false,
): Suggestion | null {
  const candidates: SuggestedLeg[] = fixtures
    .filter((f) => isSelectable(f) && (f.league.verified || demo) && f.model_probabilities)
    .map((f) => ({ fixture: f, ...topOutcome(f.model_probabilities!) }))
    .sort(
      (a, b) =>
        b.probability - a.probability ||
        a.fixture.kickoff_at.localeCompare(b.fixture.kickoff_at) ||
        a.fixture.id - b.fixture.id,
    )
    .slice(0, POOL);
  let best: SuggestedLeg[] | null = null;
  let bestProbability = -1;
  for (const legs of combinations(candidates, size)) {
    if (shareTeam(legs)) continue;
    const p = legs.reduce((acc, l) => acc * l.probability, 1);
    if (p > bestProbability) {
      best = legs;
      bestProbability = p;
    }
  }
  if (!best) return null;
  const legs = [...best].sort((a, b) => a.fixture.kickoff_at.localeCompare(b.fixture.kickoff_at));
  return {
    legs,
    selections: Object.fromEntries(legs.map((l) => [l.fixture.id, l.outcome])),
    probability: bestProbability,
  };
}
