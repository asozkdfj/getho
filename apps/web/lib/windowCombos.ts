import type { FixtureSummary, Outcome } from "@edge/contracts";

import { isSelectable, type Selections } from "./combination";
import { topOutcome } from "./confidence";

/** Matches per window searched exhaustively (the most likely outcomes first). */
const POOL = 12;

export interface WindowLeg {
  fixture: FixtureSummary;
  outcome: Outcome;
  probability: number;
  /** De-margined market probability of the same outcome, when odds exist. */
  market: number | null;
}

export interface WindowCombo {
  legs: WindowLeg[];
  selections: Selections;
  /** Product of the legs' model probabilities (independence approximation). */
  probability: number;
  /** Same product with market probabilities; null when a leg has no odds. */
  marketProbability: number | null;
  firstKickoff: string;
  lastKickoff: string;
  /** Hours between the first and the last kickoff. */
  spanHours: number;
}

function pairs<T>(items: T[]): [T, T][] {
  const out: [T, T][] = [];
  items.forEach((a, i) => items.slice(i + 1).forEach((b) => out.push([a, b])));
  return out;
}

function shareTeam(legs: WindowLeg[]): boolean {
  const teams = legs.flatMap((l) => [l.fixture.home_team.id, l.fixture.away_team.id]);
  return new Set(teams).size !== teams.length;
}

const MARKET_KEY: Record<Outcome, "home" | "draw" | "away"> = {
  HOME: "home",
  DRAW: "draw",
  AWAY: "away",
};

function toLeg(f: FixtureSummary): WindowLeg {
  const top = topOutcome(f.model_probabilities!);
  const m = f.fair_market_probabilities;
  return { fixture: f, ...top, market: m ? m[MARKET_KEY[top.outcome]] : null };
}

/**
 * The ``limit`` most likely 3-match combinations whose kickoffs all fall within
 * ``windowHours`` of each other (most likely outcome of each match, verified
 * leagues only - every league on demo data - no team twice). Combinations are
 * ranked by the product of model probabilities; the market product is shown
 * next to it. Ties: earlier first kickoff, then lower fixture ids.
 */
export function topWindowCombos(
  fixtures: FixtureSummary[],
  { size = 3, windowHours = 8, limit = 5, demo = false } = {},
): WindowCombo[] {
  const legs = fixtures
    .filter((f) => isSelectable(f) && (f.league.verified || demo) && f.model_probabilities)
    .map(toLeg)
    .sort((a, b) => a.fixture.kickoff_at.localeCompare(b.fixture.kickoff_at));
  const windowMs = windowHours * 3_600_000;
  const seen = new Map<string, WindowCombo>();
  legs.forEach((first, i) => {
    const start = Date.parse(first.fixture.kickoff_at);
    const others = legs
      .slice(i + 1)
      .filter((l) => Date.parse(l.fixture.kickoff_at) - start <= windowMs)
      .sort((a, b) => b.probability - a.probability)
      .slice(0, POOL);
    if (size !== 3) return; // the UI offers 3-match windows only
    for (const [b, c] of pairs(others)) {
      const combo = [first, b, c];
      if (shareTeam(combo)) continue;
      const key = combo
        .map((l) => l.fixture.id)
        .sort((x, y) => x - y)
        .join("-");
      if (seen.has(key)) continue;
      const ordered = [...combo].sort((x, y) =>
        x.fixture.kickoff_at.localeCompare(y.fixture.kickoff_at),
      );
      const markets = ordered.map((l) => l.market);
      const firstKickoff = ordered[0]!.fixture.kickoff_at;
      const lastKickoff = ordered[2]!.fixture.kickoff_at;
      seen.set(key, {
        legs: ordered,
        selections: Object.fromEntries(ordered.map((l) => [l.fixture.id, l.outcome])),
        probability: ordered.reduce((acc, l) => acc * l.probability, 1),
        marketProbability: markets.every((m) => m != null)
          ? markets.reduce((acc, m) => acc! * m!, 1)
          : null,
        firstKickoff,
        lastKickoff,
        spanHours: (Date.parse(lastKickoff) - Date.parse(firstKickoff)) / 3_600_000,
      });
    }
  });
  return [...seen.values()]
    .sort(
      (a, b) =>
        b.probability - a.probability ||
        a.firstKickoff.localeCompare(b.firstKickoff) ||
        a.legs
          .map((l) => l.fixture.id)
          .join()
          .localeCompare(b.legs.map((l) => l.fixture.id).join()),
    )
    .slice(0, limit);
}
