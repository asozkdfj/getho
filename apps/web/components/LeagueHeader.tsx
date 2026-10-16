import type { LeagueRef } from "@edge/contracts";
import Link from "next/link";

import { leagueLabel } from "@/lib/leagues";

import { LeagueBadge } from "./LeagueBadge";
import { LeagueMark } from "./LeagueMark";

/** League heading above a group of fixtures. */
export function LeagueHeader({ league, count }: { league: LeagueRef; count?: number }) {
  return (
    <div className="league-header">
      <Link href={`/leagues/${league.id}`} className="league-title">
        <LeagueMark league={league} />
        <span>{leagueLabel(league)}</span>
      </Link>
      <span className="league-header-meta">
        {count !== undefined && <span className="muted small">{count}경기</span>}
        <LeagueBadge league={league} />
      </span>
    </div>
  );
}
