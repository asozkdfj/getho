import { describe, expect, it } from "vitest";

import { odds, pct, signedPct, signedPoints, statusLabel, tone } from "./format";

describe("format", () => {
  it("formats probabilities as percentages", () => {
    expect(pct(0.4567)).toBe("45.7%");
    expect(pct(1)).toBe("100.0%");
    expect(pct(null)).toBe("–");
    expect(pct(Number.NaN)).toBe("–");
  });

  it("formats signed edge in percentage points and EV in percent", () => {
    expect(signedPoints(0.0123)).toBe("+1.2%p");
    expect(signedPoints(-0.05)).toBe("−5.0%p");
    expect(signedPoints(0)).toBe("±0.0%p");
    expect(signedPct(0.0512)).toBe("+5.1%");
    expect(signedPct(-0.2)).toBe("−20.0%");
  });

  it("formats odds with two decimals", () => {
    expect(odds(2.1)).toBe("2.10");
    expect(odds(undefined)).toBe("–");
  });

  it("uses a deadband so tiny differences look neutral", () => {
    expect(tone(0.002)).toBe("neutral");
    expect(tone(0.02)).toBe("positive");
    expect(tone(-0.02)).toBe("negative");
  });

  it("translates statuses", () => {
    expect(statusLabel("finished")).toBe("종료");
    expect(statusLabel("unknown")).toBe("unknown");
  });
});
