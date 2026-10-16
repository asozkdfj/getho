const FORMATS: Record<string, Intl.DateTimeFormatOptions> = {
  datetime: {
    month: "short",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  },
  time: { hour: "2-digit", minute: "2-digit" },
  date: { year: "numeric", month: "long", day: "numeric", weekday: "short" },
  day: { month: "long", day: "numeric", weekday: "short" },
  full: {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  },
};

export type TimeFormat = keyof typeof FORMATS;

export function formatInTz(iso: string, tz: string, format: TimeFormat = "datetime"): string {
  return new Intl.DateTimeFormat("ko-KR", { ...FORMATS[format], timeZone: tz }).format(
    new Date(iso),
  );
}

/** YYYY-MM-DD of an instant in a timezone (used to group fixtures by local day). */
export function localDateKey(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
}

/** "오늘", "내일" or "10월 17일 (토)" for a local day (used by the day shortcuts). */
export function dayLabel(iso: string, tz: string, now: Date = new Date()): string {
  const key = localDateKey(iso, tz);
  const today = localDateKey(now.toISOString(), tz);
  const tomorrow = localDateKey(new Date(now.getTime() + 86_400_000).toISOString(), tz);
  if (key === today) return "오늘";
  if (key === tomorrow) return "내일";
  return formatInTz(iso, tz, "day");
}
