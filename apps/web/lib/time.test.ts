import { describe, expect, it } from "vitest";

import { dayLabel, localDateKey } from "./time";

describe("day labels", () => {
  const now = new Date("2026-10-16T03:00:00Z"); // 12:00 in Seoul

  it("names today and tomorrow in the given timezone", () => {
    expect(dayLabel("2026-10-16T14:30:00Z", "Asia/Seoul", now)).toBe("오늘"); // 23:30 KST
    expect(dayLabel("2026-10-16T15:30:00Z", "Asia/Seoul", now)).toBe("내일"); // 00:30 KST next day
  });

  it("falls back to the month, day and weekday", () => {
    expect(dayLabel("2026-10-18T03:00:00Z", "Asia/Seoul", now)).toBe("10월 18일 (일)");
  });

  it("groups by the local calendar day", () => {
    expect(localDateKey("2026-10-16T15:30:00Z", "Asia/Seoul")).toBe("2026-10-17");
    expect(localDateKey("2026-10-16T15:30:00Z", "UTC")).toBe("2026-10-16");
  });
});
