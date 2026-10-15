/** Server-side config. Read at request time so one image works in every env. */
export function apiBaseUrl(): string {
  return (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

export const DEFAULT_TZ = process.env.DEFAULT_TZ ?? "Asia/Seoul";
