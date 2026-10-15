import type { Simulation } from "@edge/contracts";
import { describe, expect, it } from "vitest";

import { agreementText, newSeed, replayResultText, timeline, visibleGoals } from "./simulation";

const sim = (share: [number, number, number], model: [number, number, number]) =>
  ({
    runs: 10000,
    standard_error: 0.005,
    outcome_share: { home: share[0], draw: share[1], away: share[2] },
    model_probabilities: { home: model[0], draw: model[1], away: model[2] },
  }) as unknown as Simulation;

describe("simulation helpers", () => {
  it("says the replays agree with the analysis within sampling noise", () => {
    expect(agreementText(sim([0.452, 0.26, 0.288], [0.45, 0.26, 0.29]))).toMatch(/거의 같아요/);
    expect(agreementText(sim([0.5, 0.2, 0.3], [0.45, 0.26, 0.29]))).toMatch(/횟수를 늘리면/);
  });

  it("builds a running score timeline", () => {
    const replay = {
      home_goals: 2,
      away_goals: 1,
      goals: [
        { minute: 12, side: "home" as const },
        { minute: 40, side: "away" as const },
        { minute: 77, side: "home" as const },
      ],
    };
    const items = timeline(replay);
    expect(items.map((i) => i.score)).toEqual(["1 : 0", "1 : 1", "2 : 1"]);
    expect(visibleGoals(items, 45)).toHaveLength(2);
    expect(replayResultText(replay, "A", "B")).toBe("A 승리");
    expect(replayResultText({ ...replay, away_goals: 2 }, "A", "B")).toBe("무승부");
  });

  it("creates valid seeds", () => {
    expect(newSeed(() => 0)).toBe(0);
    expect(newSeed(() => 0.999999)).toBeLessThan(2 ** 31);
  });
});
