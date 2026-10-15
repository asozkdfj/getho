import type { Probabilities } from "@edge/contracts";

import { pct } from "@/lib/format";

/** Stacked 1X2 bar. Purely visual; the numbers are always printed alongside. */
export function ProbabilityBar({ p, label }: { p: Probabilities; label: string }) {
  return (
    <div
      className="pbar"
      role="img"
      aria-label={`${label}: 홈 ${pct(p.home)}, 무 ${pct(p.draw)}, 원정 ${pct(p.away)}`}
    >
      <span className="pbar-label">{label}</span>
      <span className="pbar-track">
        <span className="pbar-seg home" style={{ width: `${p.home * 100}%` }} />
        <span className="pbar-seg draw" style={{ width: `${p.draw * 100}%` }} />
        <span className="pbar-seg away" style={{ width: `${p.away * 100}%` }} />
      </span>
    </div>
  );
}
