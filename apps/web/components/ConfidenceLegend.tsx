import { CONFIDENCE_TEXT } from "@/lib/confidence";

/** Key for the left-edge tint of clear-cut matches (verified leagues only). */
export function ConfidenceLegend() {
  return (
    <span className="conf-legend" title="검증된 리그의 예정 경기만 표시해요">
      <span title={CONFIDENCE_TEXT.high.detail}>
        <span className="conf-swatch" aria-hidden="true" />
        {CONFIDENCE_TEXT.high.label}(65%+)
      </span>
      <span title={CONFIDENCE_TEXT.medium.detail}>
        <span className="conf-swatch medium" aria-hidden="true" />
        {CONFIDENCE_TEXT.medium.label}(55~65%)
      </span>
    </span>
  );
}
