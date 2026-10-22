import type {
  FixtureSummary,
  Outcome,
  PersonalPickIn,
  PersonalPickRevisionIn,
  PickAnalysis,
  PickSourceType,
} from "@edge/contracts";

import { OUTCOME_LABEL, pct, signedPct, signedPoints } from "./format";

export const SOURCE_LABEL: Record<PickSourceType, string> = {
  prospective_record: "경기 전 기록",
  retrospective_self_report: "사후 입력",
};

const PROB_KEY = { HOME: "home", DRAW: "draw", AWAY: "away" } as const;

/**
 * Client-made idempotency key. `crypto.randomUUID` needs a secure context
 * (https or localhost); over the private http address it is missing, so the
 * key is built from `getRandomValues`, which works everywhere.
 */
export function newRequestKey(
  random: (a: Uint8Array) => Uint8Array = (a) => crypto.getRandomValues(a),
): string {
  const bytes = random(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function offsetMinutes(utcMs: number, tz: string): number {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
      .formatToParts(new Date(utcMs))
      .map((p) => [p.type, p.value]),
  );
  const asUtc = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second),
  );
  return Math.round((asUtc - utcMs) / 60000);
}

/** "2026-10-21T19:30" read as a wall-clock time in `tz` -> ISO instant (UTC). */
export function zonedToIso(local: string, tz: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!m) return null;
  const [y, mo, d, h, mi] = m.slice(1).map(Number) as [number, number, number, number, number];
  const guess = Date.UTC(y, mo - 1, d, h, mi);
  let utc = guess - offsetMinutes(guess, tz) * 60000;
  utc = guess - offsetMinutes(utc, tz) * 60000; // settle across a DST change
  return new Date(utc).toISOString();
}

export type PickFormValues = {
  selection: Outcome | null;
  decidedNow: boolean;
  decisionLocal: string;
  entryOdds: string;
  stakeKrw: string;
  userProbabilityPct: string;
  reason: string;
  purchased: boolean;
};

export const EMPTY_FORM: PickFormValues = {
  selection: null,
  decidedNow: true,
  decisionLocal: "",
  entryOdds: "",
  stakeKrw: "",
  userProbabilityPct: "",
  reason: "",
  purchased: false,
};

type Fields = Omit<PersonalPickIn, "idempotency_key" | "fixture_id">;

/** Form strings -> request fields. Empty inputs stay empty (never 0). */
export function toFields(
  v: PickFormValues,
  tz: string,
): { fields: Fields; error: null } | { fields: null; error: string } {
  if (!v.selection) return { fields: null, error: "홈 승·무승부·원정 승 중 하나를 고르세요." };
  const fields: Fields = { selection: v.selection, self_reported_purchase: v.purchased };
  if (!v.decidedNow) {
    const iso = zonedToIso(v.decisionLocal, tz);
    if (!iso) return { fields: null, error: "결정 시각을 입력하세요." };
    fields.decision_at = iso;
  }
  if (v.entryOdds.trim()) {
    const d = Number(v.entryOdds);
    if (!/^\d+(\.\d{1,2})?$/.test(v.entryOdds.trim()) || d <= 1) {
      return { fields: null, error: "배당은 1보다 큰 숫자(소수 둘째 자리까지)로 입력하세요." };
    }
    fields.entry_odds = d;
  }
  if (v.stakeKrw.trim()) {
    const s = Number(v.stakeKrw.replace(/,/g, ""));
    if (!Number.isInteger(s) || s < 0) {
      return { fields: null, error: "금액은 0 이상의 정수(원)로 입력하세요." };
    }
    fields.stake_krw = s;
  }
  if (v.userProbabilityPct.trim()) {
    const p = Number(v.userProbabilityPct);
    if (!Number.isFinite(p) || p <= 0 || p >= 100) {
      return { fields: null, error: "내 예상 확률은 0과 100 사이(%)로 입력하세요." };
    }
    fields.user_probability = p / 100;
  }
  if (v.reason.trim()) fields.user_reason = v.reason.trim();
  return { fields, error: null };
}

export function createBody(
  fixtureId: number,
  key: string,
  v: PickFormValues,
  tz: string,
): { body: PersonalPickIn; error: null } | { body: null; error: string } {
  const r = toFields(v, tz);
  if (r.error !== null) return { body: null, error: r.error };
  return { body: { ...r.fields, idempotency_key: key, fixture_id: fixtureId }, error: null };
}

export function revisionBody(
  baseRevision: number,
  key: string,
  v: PickFormValues,
  tz: string,
): { body: PersonalPickRevisionIn; error: null } | { body: null; error: string } {
  const r = toFields(v, tz);
  if (r.error !== null) return { body: null, error: r.error };
  return { body: { ...r.fields, idempotency_key: key, base_revision: baseRevision }, error: null };
}

/** One line per risk, each with the number it rests on. Nothing is invented. */
export function riskLines(a: PickAnalysis): string[] {
  const lines: string[] = [];
  const sel = OUTCOME_LABEL[a.selection];
  if (a.model) {
    const fails = a.model.failure_outcomes
      .map((o) => `${OUTCOME_LABEL[o.outcome]} ${pct(o.probability)}`)
      .join(", ");
    lines.push(
      `모델 기준 ${sel} 확률 ${pct(a.model.selection_probability)} — 빗나갈 확률 ` +
        `${pct(a.model.failure_probability)} (${fails}).`,
    );
    if (!a.model.agrees_with_top) {
      lines.push(
        `모델이 가장 높게 본 결과는 ${OUTCOME_LABEL[a.model.top_outcome]} ` +
          `${pct(a.model.top_probability)}로, 내 선택과 달라요.`,
      );
    }
  }
  if (a.market) {
    let line = `같은 시각 시장(${a.market.bookmaker}, 마진 제거) ${sel} 확률 ${pct(
      a.market.selection_fair_probability,
    )}`;
    if (a.market.model_minus_market !== null) {
      line += ` · 모델과 차이 ${signedPoints(a.market.model_minus_market)} (의견 차이일 뿐 정답 판정이 아니에요)`;
    }
    lines.push(`${line}.`);
  }
  if (a.price) {
    let line = `입력 배당 ${a.price.entry_odds.toFixed(2)}의 손익분기 확률은 ${pct(
      a.price.break_even_probability,
    )}`;
    if (a.price.model_assumption_return !== null) {
      line += ` · 모델이 맞다는 가정의 기대수익 추정 ${signedPct(a.price.model_assumption_return)}`;
    }
    lines.push(`${line}.`);
  }
  return lines;
}

/** Plain-language warnings and missing inputs, from the stored codes. */
export function cautionLines(a: PickAnalysis): string[] {
  const out: string[] = [];
  const team = { home: a.home_team, away: a.away_team };
  for (const m of a.missing) {
    if (m.item === "model") {
      out.push("결정 시각에 저장된 모델 예측이 없어 모델 확률을 보여 줄 수 없어요.");
    } else if (m.item === "market") {
      out.push("결정 시각에 저장된 시장 배당이 없어 시장과 비교할 수 없어요.");
    } else if (m.item === "entry_odds") {
      out.push("배당을 입력하지 않아 손익분기와 수익을 계산하지 않았어요.");
    } else if (m.item === "user_probability") {
      out.push("내 예상 확률은 입력하지 않았어요 (모델 확률로 대신하지 않아요).");
    } else if (m.item === "absences_home" || m.item === "absences_away") {
      const side = m.item === "absences_home" ? "home" : "away";
      out.push(
        `${team[side]} 결장 정보는 결정 시각까지 확인되지 않았어요 (결장 없음이 아니라 미확인).`,
      );
    }
  }
  if (a.warnings.includes("market_odds_older_than_24h")) {
    out.push("비교한 시장 배당이 결정 시각보다 24시간 넘게 이전 값이에요.");
  }
  if (a.warnings.includes("league_not_verified")) {
    out.push("이 리그는 모델 정확도를 실제 결과로 검증하지 않은 리그예요.");
  }
  return out;
}

export function selectionProbability(a: PickAnalysis): number | null {
  return a.model ? a.model.probabilities[PROB_KEY[a.selection]] : null;
}

export type PickerScope = "featured" | "verified" | "all";

export interface PickerGroup {
  league: FixtureSummary["league"];
  fixtures: FixtureSummary[];
}

/** Matches a team (name or short name) or the league (name or country). */
export function matchesQuery(f: FixtureSummary, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [
    f.home_team.name,
    f.home_team.short_name,
    f.away_team.name,
    f.away_team.short_name,
    f.league.name,
    f.league.country,
    f.league.country_ko,
  ].some((s) => s.toLowerCase().includes(needle));
}

export function inScope(f: FixtureSummary, scope: PickerScope): boolean {
  if (scope === "featured") return f.league.featured;
  if (scope === "verified") return f.league.verified;
  return true;
}

/** Scope that shows something: the requested one, else the next wider one. */
export function defaultScope(fixtures: FixtureSummary[]): PickerScope {
  if (fixtures.some((f) => f.league.featured)) return "featured";
  if (fixtures.some((f) => f.league.verified)) return "verified";
  return "all";
}

/**
 * The picker's league groups: filtered by scope and search, featured leagues
 * first, then verified ones, then by country and name; matches by kickoff.
 */
export function pickerGroups(
  fixtures: FixtureSummary[],
  query: string,
  scope: PickerScope,
): PickerGroup[] {
  const groups = new Map<number, PickerGroup>();
  for (const f of fixtures) {
    if (!inScope(f, scope) || !matchesQuery(f, query)) continue;
    const g = groups.get(f.league.id) ?? { league: f.league, fixtures: [] };
    g.fixtures.push(f);
    groups.set(f.league.id, g);
  }
  const rank = (g: PickerGroup) => (g.league.featured ? 0 : g.league.verified ? 1 : 2);
  return [...groups.values()]
    .map((g) => ({
      ...g,
      fixtures: [...g.fixtures].sort(
        (a, b) => a.kickoff_at.localeCompare(b.kickoff_at) || a.id - b.id,
      ),
    }))
    .sort(
      (a, b) =>
        rank(a) - rank(b) ||
        a.league.country_ko.localeCompare(b.league.country_ko, "ko") ||
        a.league.name.localeCompare(b.league.name),
    );
}
