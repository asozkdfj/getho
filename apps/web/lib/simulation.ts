import type { Simulation, SimulationReplay } from "@edge/contracts";

import { pct } from "./format";

export const DEFAULT_RUNS = 10_000;

/** A fresh seed for "run again" (any non-negative 31-bit integer). */
export function newSeed(random: () => number = Math.random): number {
  return Math.floor(random() * 2 ** 31);
}

/** How close the simulated outcome shares are to the analysis probabilities. */
export function agreementText(sim: Simulation): string {
  const keys = ["home", "draw", "away"] as const;
  const gap = Math.max(
    ...keys.map((k) => Math.abs(sim.outcome_share[k] - sim.model_probabilities[k])),
  );
  const noise = 2 * sim.standard_error;
  return gap <= noise + 0.002
    ? `${sim.runs.toLocaleString()}번 다시 치른 결과가 분석 확률과 거의 같아요 (최대 차이 ${(gap * 100).toFixed(1)}%p, 우연 범위 ±${(noise * 100).toFixed(1)}%p).`
    : `${sim.runs.toLocaleString()}번 결과와 분석 확률의 차이가 ${(gap * 100).toFixed(1)}%p예요. 횟수를 늘리면 더 가까워져요.`;
}

export interface TimelineItem {
  minute: number;
  side: "home" | "away";
  score: string; // running score after this goal, e.g. "1 : 0"
}

/** Goals in order with the running score. */
export function timeline(replay: SimulationReplay): TimelineItem[] {
  let h = 0;
  let a = 0;
  return replay.goals.map((g) => {
    if (g.side === "home") h += 1;
    else a += 1;
    return { minute: g.minute, side: g.side, score: `${h} : ${a}` };
  });
}

/** Goals visible at a given match minute (for the step-by-step replay). */
export function visibleGoals(items: TimelineItem[], minute: number): TimelineItem[] {
  return items.filter((g) => g.minute <= minute);
}

export function replayResultText(replay: SimulationReplay, home: string, away: string): string {
  if (replay.home_goals > replay.away_goals) return `${home} 승리`;
  if (replay.home_goals < replay.away_goals) return `${away} 승리`;
  return "무승부";
}

export function shareText(share: number): string {
  return pct(share, 1);
}
