import type { Highlight, HighlightCaveat } from "@edge/contracts";

import { LARGE_GAP_CAUTION, UNVERIFIED_LEAGUE_CAUTION, promotedCaution } from "./explain";
import { pct } from "./format";

export function outcomeName(h: Highlight): string {
  if (h.outcome === "HOME") return `${h.fixture.home_team.name} 승리`;
  if (h.outcome === "AWAY") return `${h.fixture.away_team.name} 승리`;
  return "무승부";
}

export function highlightSentence(h: Highlight): string {
  return (
    `${outcomeName(h)} 가능성을 분석은 ${pct(h.model_probability, 0)}, ` +
    `시장은 ${pct(h.fair_probability, 0)}로 봐요. ` +
    `분석이 ${Math.round(h.edge * 100)}%p 더 높게 봅니다.`
  );
}

export function caveatText(caveat: HighlightCaveat, h: Highlight): string {
  switch (caveat) {
    case "promoted_home":
      return promotedCaution(h.fixture.home_team.name);
    case "promoted_away":
      return promotedCaution(h.fixture.away_team.name);
    case "large_gap":
      return LARGE_GAP_CAUTION;
    case "unverified_league":
      return UNVERIFIED_LEAGUE_CAUTION;
  }
}

/** Caveats that read the same on every card (not team-specific). */
const GENERIC: readonly HighlightCaveat[] = ["unverified_league", "large_gap"];

/**
 * Generic caveats present on every highlight: shown once above the list
 * instead of repeated on each card.
 */
export function sharedCaveats(items: Highlight[]): HighlightCaveat[] {
  if (items.length < 2) return [];
  return GENERIC.filter((c) => items.every((h) => h.caveats.includes(c)));
}

/** Wording for a caveat shown once for the whole list. */
export function sharedCaveatText(caveat: HighlightCaveat): string {
  if (caveat === "unverified_league") {
    return "아래 경기는 모두 정확도 검증 전 리그예요. 과거 기록으로 분석의 정확도를 아직 측정하지 않았어요";
  }
  return "아래 경기 모두 분석과 시장의 차이가 매우 커요. 시장은 부상·이적 같은 최신 소식을 이미 반영했을 수 있어요";
}
