import type { LeagueRef } from "@edge/contracts";

/**
 * Small league logo (or the country flag) from the data provider, if any.
 * Plain <img>: provider images are external and tiny, so next/image's
 * optimisation (and its domain allow-list) is not worth it here.
 */
export function LeagueMark({ league, size = 18 }: { league: LeagueRef; size?: number }) {
  const src = league.logo_url ?? league.flag_url;
  if (!src) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      className="league-mark"
      referrerPolicy="no-referrer"
    />
  );
}
