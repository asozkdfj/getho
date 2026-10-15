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
