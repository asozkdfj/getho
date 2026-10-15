import type { CalibrationBin } from "@edge/contracts";
import { OUTCOMES } from "@edge/contracts";

import { OUTCOME_LABEL, pct } from "@/lib/format";
import { reliabilityPoints } from "@/lib/picks";

const SIZE = 260;
const PAD = 34;
const COLOR = { HOME: "var(--home)", DRAW: "var(--draw)", AWAY: "var(--away)" } as const;

const sx = (v: number) => PAD + v * (SIZE - PAD - 10);
const sy = (v: number) => SIZE - PAD - v * (SIZE - PAD - 10);

/**
 * Reliability diagram: predicted probability (x) vs how often it happened (y).
 * Points on the diagonal mean "when the model says 60%, it happens ~60% of the time".
 */
export function CalibrationChart({ bins }: { bins: CalibrationBin[] }) {
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <figure className="calibration">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label="예측 확률과 실제 발생 비율 비교 그래프"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} y1={sy(0)} x2={sx(t)} y2={sy(1)} className="grid" />
            <line x1={sx(0)} y1={sy(t)} x2={sx(1)} y2={sy(t)} className="grid" />
            <text x={sx(t)} y={SIZE - PAD + 14} textAnchor="middle">
              {Math.round(t * 100)}
            </text>
            <text x={PAD - 6} y={sy(t) + 4} textAnchor="end">
              {Math.round(t * 100)}
            </text>
          </g>
        ))}
        <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} className="diag" />
        {OUTCOMES.map((o) => {
          const pts = reliabilityPoints(bins, o);
          return (
            <g key={o} style={{ color: COLOR[o] }}>
              <polyline
                points={pts.map((p) => `${sx(p.predicted)},${sy(p.observed)}`).join(" ")}
                fill="none"
                stroke="currentColor"
                strokeWidth={1.5}
              />
              {pts.map((p) => (
                <circle
                  key={`${p.predicted}`}
                  cx={sx(p.predicted)}
                  cy={sy(p.observed)}
                  r={Math.min(6, 2 + Math.sqrt(p.count) / 4)}
                  fill="currentColor"
                >
                  <title>
                    {`${OUTCOME_LABEL[o]}: 예측 ${pct(p.predicted, 0)} → 실제 ${pct(p.observed, 0)} (${p.count}경기)`}
                  </title>
                </circle>
              ))}
            </g>
          );
        })}
        <text x={SIZE / 2} y={SIZE - 4} textAnchor="middle">
          분석 확률(%)
        </text>
        <text x={10} y={SIZE / 2} textAnchor="middle" transform={`rotate(-90 10 ${SIZE / 2})`}>
          실제 발생(%)
        </text>
      </svg>
      <figcaption className="legend">
        {OUTCOMES.map((o) => (
          <span key={o}>
            <span className="dot" style={{ background: COLOR[o] }} />
            {OUTCOME_LABEL[o]}
          </span>
        ))}
        <span>점선 = 완벽하게 맞는 확률</span>
      </figcaption>
    </figure>
  );
}
