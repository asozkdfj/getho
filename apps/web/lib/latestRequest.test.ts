import { describe, expect, it } from "vitest";

import { LatestRequest } from "./latestRequest";

describe("latest request guard (QA-01)", () => {
  it("a new request voids and aborts the previous one", () => {
    const guard = new LatestRequest();
    const first = guard.start();
    const second = guard.start();
    expect(first.isCurrent()).toBe(false);
    expect(first.signal.aborted).toBe(true);
    expect(second.isCurrent()).toBe(true);
    expect(second.signal.aborted).toBe(false);
  });

  it("cancel (selection changed or reset) voids the running request", () => {
    const guard = new LatestRequest();
    const ticket = guard.start();
    guard.cancel();
    expect(ticket.isCurrent()).toBe(false);
    expect(ticket.signal.aborted).toBe(true);
  });
});
