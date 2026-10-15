import type { FixtureSummary, LeagueRef, LeagueSummary } from "@edge/contracts";

import { localDateKey } from "./time";

export interface Badge {
  label: string;
  tone: "positive" | "neutral" | "caution";
  title: string;
}

/** What the analysis can (and cannot) say about a league, in plain words. */
export function leagueBadge(league: LeagueRef): Badge {
  if (league.type === "cup") {
    return {
      label: "컵 대회 · 예측 없음",
      tone: "neutral",
      title: "여러 리그 팀이 섞여 있어 리그 전력표로 설명할 수 없으므로 예측하지 않아요",
    };
  }
  if (!league.predicted) {
    return {
      label: "분석 준비 중",
      tone: "neutral",
      title: "과거 경기 결과를 모으는 중이에요. 기록이 쌓이면 분석을 시작해요",
    };
  }
  if (league.verified) {
    return {
      label: "정확도 검증됨",
      tone: "positive",
      title: "과거 실제 경기로 분석의 정확도를 측정한 리그예요",
    };
  }
  return {
    label: "검증 전",
    tone: "caution",
    title: "분석은 하지만 과거 기록으로 정확도를 아직 측정하지 않은 리그예요",
  };
}

/** Longer explanation for a league page or a fixture page. */
export function leagueNote(league: LeagueRef): string | null {
  if (league.type === "cup") {
    return "컵 대회는 서로 다른 리그 팀이 맞붙어 한 리그의 전력표로 설명할 수 없어요. 그래서 분석 확률은 내지 않고 시장(배당)만 보여 드려요.";
  }
  if (!league.predicted) {
    return "이 리그는 과거 경기 결과를 모으는 중이에요. 기록이 충분히 쌓이면 자동으로 분석을 시작해요.";
  }
  if (!league.verified) {
    return "이 리그는 다른 리그와 같은 방식으로 분석하지만, 과거 기록으로 정확도를 아직 측정하지 않았어요. 오늘의 픽 후보에서도 빠져요.";
  }
  return null;
}

export function leagueLabel(league: Pick<LeagueRef, "country_ko" | "name">): string {
  return `${league.country_ko} · ${league.name}`;
}

export interface LeagueGroup {
  league: LeagueRef;
  fixtures: FixtureSummary[];
}

/** Fixtures grouped by league: featured leagues first, then by earliest kickoff. */
export function groupByLeague(fixtures: FixtureSummary[]): LeagueGroup[] {
  const groups = new Map<number, LeagueGroup>();
  for (const f of fixtures) {
    const g = groups.get(f.league.id);
    if (g) g.fixtures.push(f);
    else groups.set(f.league.id, { league: f.league, fixtures: [f] });
  }
  return [...groups.values()].sort((a, b) => {
    if (a.league.featured !== b.league.featured) return a.league.featured ? -1 : 1;
    const ka = a.fixtures[0]!.kickoff_at;
    const kb = b.fixtures[0]!.kickoff_at;
    return ka < kb ? -1 : ka > kb ? 1 : a.league.name.localeCompare(b.league.name);
  });
}

export interface DayGroup {
  day: string;
  first: string;
  leagues: LeagueGroup[];
}

export function groupByDayAndLeague(fixtures: FixtureSummary[], tz: string): DayGroup[] {
  const days = new Map<string, FixtureSummary[]>();
  for (const f of fixtures) {
    const key = localDateKey(f.kickoff_at, tz);
    days.set(key, [...(days.get(key) ?? []), f]);
  }
  return [...days.entries()].map(([day, list]) => ({
    day,
    first: list[0]!.kickoff_at,
    leagues: groupByLeague(list),
  }));
}

/** Case-insensitive search over league name and country (English and Korean). */
export function matchesQuery(league: LeagueSummary, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [league.name, league.country, league.country_ko].some((s) =>
    s.toLowerCase().includes(needle),
  );
}
