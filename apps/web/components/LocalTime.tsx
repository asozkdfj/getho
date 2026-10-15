"use client";

import { useSyncExternalStore } from "react";

import { formatInTz, type TimeFormat } from "@/lib/time";

const subscribe = () => () => {};
const browserTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

/**
 * Renders a UTC instant in the viewer's timezone. The server (and the first
 * client render) use `fallbackTz` so hydration matches; afterwards the
 * browser's own timezone is used.
 */
export function LocalTime({
  iso,
  fallbackTz,
  format = "datetime",
}: {
  iso: string;
  fallbackTz: string;
  format?: TimeFormat;
}) {
  const tz = useSyncExternalStore(subscribe, browserTz, () => fallbackTz);
  return (
    <time dateTime={iso} title={`${iso} (UTC 기준 저장)`}>
      {formatInTz(iso, tz, format)}
    </time>
  );
}
