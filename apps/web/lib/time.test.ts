import { describe, expect, it } from "vitest";

import { dayLabel, displayTimeZone, formatInTz, localDateKey } from "./time";

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

describe("time zone of a kickoff under a date heading (QA-04)", () => {
  // 00:30 on the 17th in Seoul is 16:30 on the 16th in London
  const kickoff = "2026-10-16T15:30:00Z";

  it("keeps the grouping zone for time-only labels", () => {
    const tz = displayTimeZone(true, "Europe/London", "Asia/Seoul");
    expect(localDateKey(kickoff, tz)).toBe("2026-10-17"); // same day as its heading
    expect(formatInTz(kickoff, tz, "time")).toBe(formatInTz(kickoff, "Asia/Seoul", "time"));
  });

  it("uses the viewer's zone otherwise", () => {
    expect(displayTimeZone(false, "Europe/London", "Asia/Seoul")).toBe("Europe/London");
  });
});
