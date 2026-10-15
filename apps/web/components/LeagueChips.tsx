import type { LeagueSummary } from "@edge/contracts";
import Link from "next/link";

import { LeagueMark } from "./LeagueMark";

/** Horizontal, scrollable list of league shortcuts. */
export function LeagueChips({
  leagues,
  more = true,
}: {
  leagues: LeagueSummary[];
  more?: boolean;
}) {
  return (
    <nav className="league-chips" aria-label="리그 바로가기">
      {leagues.map((lg) => (
        <Link key={lg.id} href={`/leagues/${lg.id}`} className="chip">
          <LeagueMark league={lg} size={16} />
          {lg.name}
          <span className="chip-count">{lg.upcoming_count}</span>
        </Link>
      ))}
      {more && (
        <Link href="/leagues" className="chip chip-more">
          전체 리그 →
        </Link>
      )}
    </nav>
  );
}
