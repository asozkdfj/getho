import type {
  CalibrationBin,
  Outcome,
  PickHistory,
  TodayPick,
  TodayPickStatus,
} from "@edge/contracts";

import { pct } from "./format";

/**
 * Wording for Today's Pick. Every sentence is built from values the model
 * actually used (stored with the pick); nothing here invents a reason or a
 * probability, and nothing promises a result.
 */

export function pickOutcomeText(outcome: Outcome, home: string, away: string): string {
  if (outcome === "HOME") return `${home} 승리`;
  if (outcome === "AWAY") return `${away} 승리`;
  return "무승부";
}

export interface StatusInfo {
  label: string;
  tone: "positive" | "negative" | "neutral";
  description: string;
}

export function pickStatusInfo(status: TodayPickStatus, threshold: number): StatusInfo {
  switch (status) {
    case "scheduled":
      return {
        label: "선정 전",
        tone: "neutral",
        description: "오늘의 픽은 정해진 시각에 한 번 선정되고, 그 뒤로는 바뀌지 않아요.",
      };
    case "published":
      return {
        label: "선정됨 · 경기 전",
        tone: "neutral",
        description: "선정 당시의 확률을 그대로 보여 줍니다. 새로고침해도 바뀌지 않아요.",
      };
    case "settled":
      return { label: "경기 종료", tone: "neutral", description: "경기 결과가 기록됐어요." };
    case "voided":
      return {
        label: "무효",
        tone: "negative",
        description:
          "선정한 경기가 취소·연기되어 이 픽은 무효 처리됐어요. 적중률 계산에서 빠집니다.",
      };
    case "no_qualifying_match":
      return {
        label: "오늘은 픽 없음",
        tone: "neutral",
        description:
          `데이터 점검을 통과하면서 분석 확률이 기준(${pct(threshold, 0)}) 이상인 경기가 ` +
          "이번 픽 시간대에는 없었어요. 억지로 고르지 않는 것도 규칙입니다.",
      };
    case "no_matches":
      return {
        label: "경기 없음",
        tone: "neutral",
        description: "이번 픽 시간대(오전 9시~다음 날 오전 9시)에 예정된 경기가 없어요.",
      };
  }
}

type Features = Record<string, unknown>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Elo gaps below this (~0.1 goal) are described as "similar" rather than "stronger". */
export const ELO_SIMILAR = 25;

const NEWCOMER_PRIORS = new Set(["promoted_relegation_level", "unseen_relegation_level"]);

/**
 * Template explanation. Only factors listed in `factors_used` (and present in
 * the stored features) produce a sentence.
 */
export function pickReasons(pick: TodayPick): string[] {
  const f = pick.fixture;
  if (!f || !pick.outcome) return [];
  const home = f.home_team.name;
  const away = f.away_team.name;
  const features = (pick.features ?? {}) as Features;
  const used = new Set(pick.factors_used);
  const reasons: string[] = [];

  const eloHome = num(features.elo_home);
  const eloAway = num(features.elo_away);
  const eloDiff = num(features.elo_diff_incl_hfa);
  if (used.has("team_strength_elo") && eloHome !== null && eloAway !== null) {
    const gap = Math.abs(eloHome - eloAway);
    const verdict =
      gap < ELO_SIMILAR
        ? "두 팀의 누적 전력은 비슷해요."
        : `${eloHome > eloAway ? home : away}의 누적 전력이 더 높아요.`;
    reasons.push(
      `전력 점수(Elo): ${home} ${Math.round(eloHome)} · ${away} ${Math.round(eloAway)} — ${verdict}`,
    );
  }
  if (used.has("home_advantage") && eloDiff !== null && eloHome !== null && eloAway !== null) {
    const hfa = eloDiff - (eloHome - eloAway);
    if (hfa > 0) {
      reasons.push(`홈 경기 이점(전력 점수 +${Math.round(hfa)})을 ${home}에 더해 계산했어요.`);
    }
  }
  const attH = num(features.attack_home);
  const defH = num(features.defence_home);
  const attA = num(features.attack_away);
  const defA = num(features.defence_away);
  if (used.has("attack_defence_strength") && attH !== null && attA !== null) {
    const parts = [
      `${home} 득점력 ${attH.toFixed(2)}`,
      defH !== null ? `실점 ${defH.toFixed(2)}` : null,
      `${away} 득점력 ${attA.toFixed(2)}`,
      defA !== null ? `실점 ${defA.toFixed(2)}` : null,
    ].filter(Boolean);
    reasons.push(`최근 경기 기준 득점·실점 수준(리그 평균 = 1.00): ${parts.join(", ")}.`);
  }
  if (pick.expected_goals) {
    reasons.push(
      `이를 합쳐 예상 골은 ${home} ${pick.expected_goals.home.toFixed(2)} : ` +
        `${pick.expected_goals.away.toFixed(2)} ${away}로 계산됐어요.`,
    );
  }
  return reasons;
}

export function pickCautions(pick: TodayPick): string[] {
  const f = pick.fixture;
  if (!f) return [];
  const features = (pick.features ?? {}) as Features;
  const out: string[] = [];
  for (const [key, team] of [
    ["prior_home", f.home_team.name],
    ["prior_away", f.away_team.name],
  ] as const) {
    if (NEWCOMER_PRIORS.has(String(features[key]))) {
      out.push(`${team}: 승격팀이라 이번 시즌 데이터가 적어 분석이 덜 정확할 수 있어요`);
    }
  }
  out.push("부상·이적·감독 교체 같은 최신 소식은 분석에 들어가 있지 않아요");
  return out;
}

const REASON_TEXT: Record<string, string> = {
  upcoming: "이미 시작했거나 끝난 경기",
  ingestion_recent: "최근 데이터 수집이 오래됨",
  prediction_available: "분석 결과 없음",
  current_model: "현재 모델로 계산된 결과가 아님",
  probabilities_valid: "확률 값 이상",
  odds_fresh: "배당 정보가 오래됨",
  team_history: "팀 경기 기록이 부족함",
  below_min_probability: "기준 확률 미달",
};

/**
 * On a no-pick day: the strongest outcome that passed every data check but
 * stayed under the threshold (null if none).
 */
export function closestCandidate(pick: TodayPick): string | null {
  const near = (pick.candidates ?? [])
    .filter(
      (c) => c.best_outcome && c.best_probability !== null && c.best_probability !== undefined,
    )
    .filter((c) => c.excluded_reasons.every((r) => r === "below_min_probability"))
    .sort((a, b) => b.best_probability! - a.best_probability!)[0];
  if (!near) return null;
  return (
    `이번 시간대에 가장 높았던 분석 확률: ${near.home} vs ${near.away} — ` +
    `${pickOutcomeText(near.best_outcome!, near.home, near.away)} ${pct(near.best_probability, 0)}` +
    ` (기준 ${pct(pick.threshold, 0)})`
  );
}

export function excludedReasonText(reason: string): string {
  return REASON_TEXT[reason] ?? reason;
}

const CHECK_LABEL: Record<string, string> = {
  upcoming: "경기 시작 전",
  ingestion_recent: "최근 데이터 수집 성공",
  prediction_available: "분석 결과 있음",
  current_model: "현재 모델 버전",
  probabilities_valid: "확률 합계·범위 정상",
  odds_fresh: "배당 정보 최신",
  team_history: "두 팀 경기 기록 충분",
};

export function qualityCheckLabel(name: string): string {
  return CHECK_LABEL[name] ?? name;
}

export function voidReasonText(reason: string | null | undefined): string {
  if (!reason) return "";
  if (reason.includes("cancelled")) return "경기 취소";
  if (reason.includes("postponed")) return "경기 연기";
  return reason;
}

/** "71% (65–77%)" style range; returns "–" when unavailable. */
export function rateWithCi(rate: number | null | undefined, ci: number[] | null | undefined) {
  if (rate === null || rate === undefined) return "–";
  if (!ci || ci.length !== 2) return pct(rate, 0);
  return `${pct(rate, 0)} (${pct(ci[0], 0)}–${pct(ci[1], 0)})`;
}

export function historySummaryText(h: PickHistory): string {
  const s = h.summary;
  const late = s.late_recorded;
  const lateNote = late > 0 ? ` 경기 시작 후에 기록된 픽 ${late}개는 성과에서 뺐어요.` : "";
  if (s.settled === 0) {
    return `아직 결과가 나온 픽이 없어요. 기록이 쌓이면 적중률을 보여 드릴게요.${lateNote}`;
  }
  const base =
    `결과가 나온 ${s.settled}개 중 ${s.hits}개 적중(${rateWithCi(s.hit_rate, s.hit_rate_ci)}), ` +
    `선정 당시 평균 분석 확률 ${pct(s.mean_probability, 0)}.`;
  return (s.settled < 30 ? `${base} 아직 표본이 작아 우연의 영향이 커요.` : base) + lateNote;
}

export interface ReliabilityPoint {
  predicted: number;
  observed: number;
  count: number;
}

/** Calibration points for one outcome, skipping empty bins. */
export function reliabilityPoints(bins: CalibrationBin[], outcome: Outcome): ReliabilityPoint[] {
  return bins
    .filter((b) => b.outcome === outcome && b.count > 0)
    .filter((b) => b.mean_predicted !== null && b.observed_frequency !== null)
    .map((b) => ({
      predicted: b.mean_predicted as number,
      observed: b.observed_frequency as number,
      count: b.count,
    }));
}

const MODEL_NAME: Record<string, string> = {
  base_rate: "기본 비율(홈/무/원정 평균)",
  elo_only: "전력 점수(Elo)만",
  poisson_only: "득점·실점(Poisson)만",
  production: "현재 서비스 모델",
  production_no_promoted_prior: "현재 모델에서 승격팀 보정만 뺀 것",
  candidate: "튜닝 후보",
  candidate_calibrated: "튜닝 후보 + 온도 보정",
  market: "시장(배당)",
};

export function modelName(name: string): string {
  return MODEL_NAME[name] ?? name;
}

/** Split labels from the report (">= 2023-24", "2020-21 .. < 2023-24") in plain words. */
export function periodText(period: string | null | undefined): string {
  if (!period) return "과거";
  const from = /^>=\s*(\S+)$/.exec(period);
  if (from) return `${from[1]} 시즌부터 지금까지`;
  const range = /^(\S+)\s*\.\.\s*<\s*(\S+)$/.exec(period);
  if (range) return `${range[1]} 시즌부터 ${range[2]} 시즌 전까지`;
  const before = /^<\s*(\S+)$/.exec(period);
  if (before) return `${before[1]} 시즌 이전`;
  return period;
}

export function thresholdText(t: number): string {
  return t <= 0 ? "기준 확률 없음" : `기준 ${pct(t, 0)}`;
}

/** "실제 EPL 경기" / "검증된 10개 리그의 실제 경기" for the backtest sentence. */
export function backtestScope(leagues: string[] | null | undefined): string {
  if (!leagues || leagues.length === 0) return "실제 경기";
  if (leagues.length === 1) return `실제 ${leagues[0]} 경기`;
  return `검증된 ${leagues.length}개 리그의 실제 경기`;
}

/** How the pick rule was replayed: the service's timing or the older whole-day count. */
export function backtestTimingText(decisionHour: number | null | undefined): string {
  if (decisionHour === null || decisionHour === undefined) {
    return "그날 모든 경기를 후보로 본 계산이라, 실제 서비스보다 픽이 나오는 날이 많게 나와요.";
  }
  const hour = hourText(decisionHour);
  return `서비스처럼 ${hour}에 그때부터 다음 날 ${hour}까지 시작하는 경기만 후보로 보고 다시 계산했어요(배당·수집 상태 점검은 재현하지 않음).`;
}

/**
 * Failed data checks worth showing next to an upcoming match's analysis
 * (QA-05). After kickoff the checks fail by nature (the match is no longer
 * upcoming, odds stop updating), so nothing is shown: the analysis on the page
 * is the one saved before kickoff.
 */
export function qualityWarnings(
  quality: { ok: boolean; checks: { name: string; passed: boolean }[] } | null | undefined,
  status: string,
): string[] {
  if (!quality || quality.ok || status !== "scheduled") return [];
  return quality.checks
    .filter((c) => !c.passed)
    .map((c) => `${qualityCheckLabel(c.name)} 확인 안 됨`);
}

/** 9 -> "오전 9시", 12 -> "낮 12시", 21 -> "오후 9시", 0 -> "자정". */
export function hourText(hour: number): string {
  if (hour === 0) return "자정";
  if (hour === 12) return "낮 12시";
  return hour < 12 ? `오전 ${hour}시` : `오후 ${hour - 12}시`;
}

/** "오전 9시 ~ 다음 날 오전 9시 경기" from the pick window start (pick time zone). */
export function pickWindowText(windowStart: string | null | undefined, tz: string): string {
  if (!windowStart) return "";
  const hour = Number(
    new Intl.DateTimeFormat("en-US", { hour: "numeric", hourCycle: "h23", timeZone: tz }).format(
      new Date(windowStart),
    ),
  );
  return `${hourText(hour)} ~ 다음 날 ${hourText(hour)} 경기`;
}
