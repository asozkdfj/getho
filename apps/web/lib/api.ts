import "server-only";

import type {
  DataStatus,
  FixtureDetail,
  FixtureList,
  HighlightList,
  LeagueList,
  LeagueSummary,
  Performance,
  PickHistory,
  Prediction,
  TodayPick,
} from "@edge/contracts";

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

export function fetchFixtures(params: {
  days: number;
  tz: string;
  date?: string;
  leagueId?: number;
  featured?: boolean;
}) {
  const q = new URLSearchParams({ days: String(params.days), tz: params.tz });
  if (params.date) q.set("date", params.date);
  if (params.leagueId !== undefined) q.set("league_id", String(params.leagueId));
  if (params.featured) q.set("featured", "true");
  return getJson<FixtureList>(`/fixtures?${q.toString()}`);
}

export function fetchLeagues(params: { days?: number; activeOnly?: boolean } = {}) {
  const q = new URLSearchParams({
    days: String(params.days ?? 7),
    active_only: String(params.activeOnly ?? true),
  });
  return getJson<LeagueList>(`/leagues?${q.toString()}`);
}

/** Returns null when the league does not exist (404). */
export async function fetchLeague(id: number): Promise<LeagueSummary | null> {
  try {
    return await getJson<LeagueSummary>(`/leagues/${id}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
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

export function fetchHighlights(params: { days?: number; limit?: number; leagueId?: number } = {}) {
  const q = new URLSearchParams({
    days: String(params.days ?? 7),
    limit: String(params.limit ?? 3),
  });
  if (params.leagueId !== undefined) q.set("league_id", String(params.leagueId));
  return getJson<HighlightList>(`/highlights?${q.toString()}`);
}

export function fetchTodayPick() {
  return getJson<TodayPick>("/picks/today");
}

export function fetchPickHistory(limit = 60) {
  return getJson<PickHistory>(`/picks/history?limit=${limit}`);
}

export function fetchPerformance() {
  return getJson<Performance>("/performance");
}

export function fetchDataStatus() {
  return getJson<DataStatus>("/status/data");
}

/** Resolves to null instead of throwing, so one failing panel never blanks the page. */
export async function orNull<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch {
    return null;
  }
}
