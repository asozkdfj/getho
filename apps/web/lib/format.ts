import type { Outcome } from "@edge/contracts";

export const OUTCOME_LABEL: Record<Outcome, string> = {
  HOME: "홈 승",
  DRAW: "무승부",
  AWAY: "원정 승",
};

export const OUTCOME_SHORT: Record<Outcome, string> = { HOME: "1", DRAW: "X", AWAY: "2" };

const STATUS_LABEL: Record<string, string> = {
  scheduled: "예정",
  live: "진행 중",
  finished: "종료",
  postponed: "연기",
  cancelled: "취소",
};

const PROVIDER_LABEL: Record<string, string> = {
  mock: "합성(mock) 데모 데이터 — 실제 경기와 무관",
  api_football: "API-Football",
};

export function providerLabel(provider: string): string {
  return PROVIDER_LABEL[provider] ?? provider;
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** 0.4567 -> "45.7%" */
export function pct(p: number | null | undefined, digits = 1): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "–";
  return `${(p * 100).toFixed(digits)}%`;
}

/** 0.0123 -> "+1.2%p" (percentage points, used for edge) */
export function signedPoints(x: number, digits = 1): string {
  const v = x * 100;
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  return `${sign}${Math.abs(v).toFixed(digits)}%p`;
}

/** 0.0512 -> "+5.1%" (used for EV per unit staked) */
export function signedPct(x: number, digits = 1): string {
  const v = x * 100;
  const sign = v > 0 ? "+" : v < 0 ? "−" : "±";
  return `${sign}${Math.abs(v).toFixed(digits)}%`;
}

export function odds(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  return x.toFixed(2);
}

export type Tone = "positive" | "negative" | "neutral";

/** Colour hint only. Tiny differences are shown as neutral to avoid false precision. */
export function tone(x: number, deadband = 0.005): Tone {
  if (x > deadband) return "positive";
  if (x < -deadband) return "negative";
  return "neutral";
}
