import type { FixtureSummary, Outcome } from "@edge/contracts";

import { isSelectable, type Selections } from "./combination";

/** Matches per window searched exhaustively (the strongest legs first). */
const POOL = 12;

export const WINDOW_HOURS = [4, 8, 12] as const;
export type WindowHours = (typeof WINDOW_HOURS)[number];

/** Which probability picks each leg's outcome and ranks the combinations. */
export type RankBasis = "model" | "market" | "average";
/** How often one match may appear across the listed combinations. */
export type Overlap = "any" | "max2" | "none";

export interface WindowLeg {
  fixture: FixtureSummary;
  outcome: Outcome;
  /** Model probability of the chosen outcome. */
  probability: number;
  /** De-margined market probability of the same outcome, when odds exist. */
  market: number | null;
  /** Probability on the ranking basis. */
  score: number;
}

export interface WindowCombo {
  legs: WindowLeg[];
  selections: Selections;
  /** Product of the legs' model probabilities (independence approximation). */
  probability: number;
  /** Same product with market probabilities; null when a leg has no odds. */
  marketProbability: number | null;
  /** Product on the ranking basis (what the list is sorted by). */
  score: number;
  firstKickoff: string;
  lastKickoff: string;
  /** Hours between the first and the last kickoff. */
  spanHours: number;
}

export interface WindowOptions {
  windowHours?: number;
  limit?: number;
  demo?: boolean;
  basis?: RankBasis;
  overlap?: Overlap;
}

type Probs = { home: number; draw: number; away: number };
const ORDER: [Outcome, keyof Probs][] = [
  ["HOME", "home"],
  ["AWAY", "away"],
  ["DRAW", "draw"],
]; // ties: HOME > AWAY > DRAW, like the pick rule

function basisProbs(f: FixtureSummary, basis: RankBasis): Probs | null {
  const model = f.model_probabilities ?? null;
  const market = f.fair_market_probabilities ?? null;
  if (basis === "model") return model;
  if (basis === "market") return market;
  if (!model || !market) return null;
  return {
    home: (model.home + market.home) / 2,
    draw: (model.draw + market.draw) / 2,
    away: (model.away + market.away) / 2,
  };
}

function toLeg(f: FixtureSummary, basis: RankBasis): WindowLeg | null {
  const p = basisProbs(f, basis);
  if (!p || !f.model_probabilities) return null;
  const [outcome, key] = ORDER.reduce((best, cur) => (p[cur[1]] > p[best[1]] ? cur : best));
  const market = f.fair_market_probabilities;
  return {
    fixture: f,
    outcome,
    probability: f.model_probabilities[key],
    market: market ? market[key] : null,
    score: p[key],
  };
}

function shareTeam(legs: WindowLeg[]): boolean {
  const teams = legs.flatMap((l) => [l.fixture.home_team.id, l.fixture.away_team.id]);
  return new Set(teams).size !== teams.length;
}

function product(values: (number | null)[]): number | null {
  return values.every((v) => v != null) ? values.reduce((a, v) => a! * v!, 1) : null;
}

/** Every 3-match combination whose kickoffs fit within ``windowHours``. */
function candidates(legs: WindowLeg[], windowHours: number): WindowCombo[] {
  const windowMs = windowHours * 3_600_000;
  const seen = new Map<string, WindowCombo>();
  legs.forEach((first, i) => {
    const start = Date.parse(first.fixture.kickoff_at);
    const others = legs
      .slice(i + 1)
      .filter((l) => Date.parse(l.fixture.kickoff_at) - start <= windowMs)
      .sort((a, b) => b.score - a.score)
      .slice(0, POOL);
    others.forEach((b, j) => {
      for (const c of others.slice(j + 1)) {
        const combo = [first, b, c];
        if (shareTeam(combo)) continue;
        const ordered = [...combo].sort((x, y) =>
          x.fixture.kickoff_at.localeCompare(y.fixture.kickoff_at),
        );
        const key = ordered.map((l) => l.fixture.id).join("-");
        if (seen.has(key)) continue;
        const firstKickoff = ordered[0]!.fixture.kickoff_at;
        const lastKickoff = ordered[2]!.fixture.kickoff_at;
        seen.set(key, {
          legs: ordered,
          selections: Object.fromEntries(ordered.map((l) => [l.fixture.id, l.outcome])),
          probability: product(ordered.map((l) => l.probability))!,
          marketProbability: product(ordered.map((l) => l.market)),
          score: product(ordered.map((l) => l.score))!,
          firstKickoff,
          lastKickoff,
          spanHours: (Date.parse(lastKickoff) - Date.parse(firstKickoff)) / 3_600_000,
        });
      }
    });
  });
  return [...seen.values()];
}

/**
 * The ``limit`` most likely 3-match combinations whose kickoffs all fall within
 * ``windowHours`` of each other. Each match contributes its most likely outcome
 * on the ranking ``basis`` (model, market, or their average); verified leagues
 * only (every league on demo data); no team twice in a combination. ``overlap``
 * limits how often one match appears across the list (greedy, best first).
 * Ties: earlier first kickoff, then lower fixture ids.
 */
export function topWindowCombos(
  fixtures: FixtureSummary[],
  {
    windowHours = 8,
    limit = 5,
    demo = false,
    basis = "model",
    overlap = "any",
  }: WindowOptions = {},
): WindowCombo[] {
  const legs = fixtures
    .filter((f) => isSelectable(f) && (f.league.verified || demo))
    .map((f) => toLeg(f, basis))
    .filter((l): l is WindowLeg => l !== null)
    .sort((a, b) => a.fixture.kickoff_at.localeCompare(b.fixture.kickoff_at));
  const ranked = candidates(legs, windowHours).sort(
    (a, b) =>
      b.score - a.score ||
      a.firstKickoff.localeCompare(b.firstKickoff) ||
      a.legs
        .map((l) => l.fixture.id)
        .join("-")
        .localeCompare(b.legs.map((l) => l.fixture.id).join("-")),
  );
  const cap = overlap === "any" ? Infinity : overlap === "max2" ? 2 : 1;
  const used = new Map<number, number>();
  const out: WindowCombo[] = [];
  for (const combo of ranked) {
    if (out.length >= limit) break;
    if (combo.legs.some((l) => (used.get(l.fixture.id) ?? 0) >= cap)) continue;
    combo.legs.forEach((l) => used.set(l.fixture.id, (used.get(l.fixture.id) ?? 0) + 1));
    out.push(combo);
  }
  return out;
}
