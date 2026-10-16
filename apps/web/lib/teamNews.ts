import type { TeamNewsSide } from "@edge/contracts";

const POSITION: Record<string, string> = { G: "골키퍼", D: "수비", M: "미드필더", F: "공격" };

export function positionLabel(pos: string | null | undefined): string {
  if (!pos) return "";
  return POSITION[pos] ?? pos;
}

const REASON: Record<string, string> = {
  injury: "부상",
  suspended: "징계",
  suspension: "징계",
  "red card": "징계",
  illness: "질병",
};

/** Provider reasons are free text in English; translate the common ones. */
export function reasonLabel(reason: string | null | undefined): string {
  if (!reason) return "";
  const key = reason.trim().toLowerCase();
  for (const [k, v] of Object.entries(REASON)) {
    if (key.includes(k)) return v;
  }
  return reason;
}

/** One plain sentence about a team's line-up news. */
export function sideSummary(side: TeamNewsSide): string {
  const starters = side.starters ?? [];
  const absences = side.absences ?? [];
  const missing = side.missing_regulars ?? [];
  const named = (names: { name: string; reason?: string | null }[]) =>
    names.map((m) => (m.reason ? `${m.name}(${reasonLabel(m.reason)})` : m.name)).join(", ");
  if (starters.length > 0) {
    if (!side.regulars_known)
      return "선발 명단이 발표됐어요. 평소 주전을 판단할 기록은 아직 부족해요.";
    if (missing.length === 0) return "평소 주전 11명이 모두 선발로 나와요.";
    return `평소 주전 11명 중 ${11 - missing.length}명이 선발이에요. 빠진 주전: ${named(missing)}`;
  }
  if (absences.length === 0) return "아직 알려진 결장 선수가 없어요.";
  if (!side.regulars_known) {
    return `결장·출전 불투명 ${absences.length}명 (주전인지 판단할 출전 기록이 아직 부족해요)`;
  }
  // missing_regulars holds confirmed absences only; a doubtful regular is not "missing" yet
  const doubtful = absences.filter((a) => a.regular && a.status !== "out");
  const parts: string[] = [];
  if (missing.length > 0) parts.push(`주전 ${missing.length}명 결장 예정: ${named(missing)}`);
  if (doubtful.length > 0) parts.push(`주전 ${doubtful.length}명 출전 불투명: ${named(doubtful)}`);
  if (parts.length > 0) return parts.join(" · ");
  return `결장·출전 불투명 ${absences.length}명 (평소 주전은 아님)`;
}
