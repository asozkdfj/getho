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
