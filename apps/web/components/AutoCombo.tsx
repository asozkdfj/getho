"use client";

import { MAX_COMBINATION_LEGS, MIN_COMBINATION_LEGS, type FixtureSummary } from "@edge/contracts";
import { useState } from "react";

import { suggestCombination } from "@/lib/autoCombo";
import type { Selections } from "@/lib/combination";
import { pct } from "@/lib/format";

const SIZES = Array.from(
  { length: MAX_COMBINATION_LEGS - MIN_COMBINATION_LEGS + 1 },
  (_, i) => MIN_COMBINATION_LEGS + i,
);

/** "Find the most likely combination" for a chosen number of matches. */
export function AutoCombo({
  fixtures,
  scopeLabel,
  demo = false,
  onApply,
}: {
  /** Matches to choose from (already narrowed to the selected league, if any). */
  fixtures: FixtureSummary[];
  scopeLabel: string;
  demo?: boolean;
  onApply: (selections: Selections) => void;
}) {
  const [size, setSize] = useState(MAX_COMBINATION_LEGS);
  const [message, setMessage] = useState<string | null>(null);
  const bookmaker = fixtures.find((f) => f.prediction_odds)?.prediction_odds?.bookmaker;

  function find() {
    const s = suggestCombination(fixtures, size, demo);
    if (!s) {
      setMessage(
        `${scopeLabel}에서 조합할 수 있는 ${demo ? "" : "검증 리그 "}경기가 ${size}개보다 적어요.`,
      );
      return;
    }
    setMessage(
      `${scopeLabel}에서 분석 확률이 가장 높은 결과 ${size}개를 골랐어요 (모두 맞을 확률 약 ${pct(s.probability, 0)}).`,
    );
    onApply(s.selections);
  }

  return (
    <section className="card auto-combo" aria-label="자동 조합">
      <h2>자동 조합</h2>
      <p className="muted small" style={{ margin: 0 }}>
        경기 수를 고르면, {demo ? "데모 경기" : "정확도를 검증한 리그 경기"} 중{" "}
        <strong>모두 맞을 확률(분석)이 가장 높은</strong> 조합을 찾아 바로 분석해요. 같은 팀이 두 번
        들어가지 않게 골라요.
      </p>
      <div className="auto-combo-row">
        <label className="small">
          경기 수
          <select value={size} onChange={(e) => setSize(Number(e.target.value))}>
            {SIZES.map((n) => (
              <option key={n} value={n}>
                {n}경기
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn" onClick={find}>
          가장 확률 높은 조합 찾기
        </button>
      </div>
      {message && (
        <p className="small" role="status" style={{ margin: "0 0 6px" }}>
          {message}
        </p>
      )}
      <p className="muted small" style={{ margin: 0 }}>
        확률이 높은 조합일수록 배당은 낮아요. 배당은 {bookmaker ?? "수집한 북메이커"} 기준이고, 국내
        배당은 보통 이보다 낮습니다. 결과를 보장하지 않으며 베팅을 권유하지 않아요.
      </p>
    </section>
  );
}
