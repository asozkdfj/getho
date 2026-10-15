import type { LeagueRef } from "@edge/contracts";

import { leagueBadge } from "@/lib/leagues";

export function LeagueBadge({ league }: { league: LeagueRef }) {
  const b = leagueBadge(league);
  return (
    <span className={`league-badge ${b.tone}`} title={b.title}>
      {b.label}
    </span>
  );
}
