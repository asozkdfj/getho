import "server-only";

import type { FixtureDetail, FixtureList, Prediction } from "@edge/contracts";

import { apiBaseUrl } from "./config";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    cache: "no-store", // probabilities/odds must never be served stale from a cache
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) {
    throw new ApiError(res.status, `API ${path} responded ${res.status}`);
  }
  return (await res.json()) as T;
}

export function fetchFixtures(params: { days: number; tz: string; date?: string }) {
  const q = new URLSearchParams({ days: String(params.days), tz: params.tz });
  if (params.date) q.set("date", params.date);
  return getJson<FixtureList>(`/fixtures?${q.toString()}`);
}

export function fetchFixture(id: number) {
  return getJson<FixtureDetail>(`/fixtures/${id}`);
}

/** Returns null when the fixture has no prediction yet (404). */
export async function fetchPrediction(id: number): Promise<Prediction | null> {
  try {
    return await getJson<Prediction>(`/fixtures/${id}/prediction`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
