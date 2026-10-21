import type { PickAnalysis, PickTeamNewsSide } from "@edge/contracts";

import { OUTCOME_LABEL, odds, pct } from "@/lib/format";
import { cautionLines, riskLines } from "@/lib/personalPicks";

import { LocalTime } from "./LocalTime";

const ABSENCE_STATUS = {
  reported: "결장·불투명 선수 보고됨",
  none_reported: "확인 결과 보고된 결장 없음",
  unknown: "미확인",
} as const;

function NewsSide({ side }: { side: PickTeamNewsSide }) {
  const absences = side.absences ?? [];
  const missing = side.missing_regulars ?? [];
  return (
    <div>
      <strong>{side.team_name}</strong>
      <div className="muted small">{ABSENCE_STATUS[side.absences_status]}</div>
      {absences.length > 0 && <div className="small">{absences.join(", ")}</div>}
      {missing.length > 0 && <div className="small">주전 이탈: {missing.join(", ")}</div>}
    </div>
  );
}

/** The frozen pre-match analysis of one revision: numbers, sources and gaps. */
export function PickAnalysisView({ a, tz }: { a: PickAnalysis; tz: string }) {
  const risks = riskLines(a);
  const cautions = cautionLines(a);
  return (
    <div className="stack">
      <p className="muted small" style={{ margin: 0 }}>
        <LocalTime iso={a.as_of} fallbackTz={tz} format="full" /> 시점까지 저장된 정보로 만든
        분석이에요. 저장 후에는 다시 계산하지 않아요 (늦게 들어온 예측·배당·결과는 반영 안 됨).
      </p>
      {risks.length > 0 ? (
        <ul className="pick-reasons">
          {risks.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <p className="small">결정 시각 기준 모델·시장 수치가 없어 확률 분석을 보여 줄 수 없어요.</p>
      )}
      {cautions.length > 0 && (
        <ul className="caveats">
          {cautions.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <div className="grid-2">
        <NewsSide side={a.team_news.home} />
        <NewsSide side={a.team_news.away} />
      </div>
      <dl className="kv small">
        <dt>모델 확률</dt>
        <dd>
          {a.model
            ? `홈 ${pct(a.model.probabilities.home)} · 무 ${pct(a.model.probabilities.draw)} · 원정 ${pct(a.model.probabilities.away)} (v${a.model.model_version}, 예측 #${a.model.prediction_id})`
            : "없음"}
        </dd>
        <dt>시장 배당</dt>
        <dd>
          {a.market ? (
            <>
              {OUTCOME_LABEL[a.selection]} {odds(a.market.selection_odds)} · 결정{" "}
              {Math.round(a.market.age_minutes)}분 전 수집 (#{a.market.odds_snapshot_id})
            </>
          ) : (
            "없음"
          )}
        </dd>
        <dt>리그 검증</dt>
        <dd>{a.league_verified ? "검증된 리그" : "미검증 리그"}</dd>
        <dt>분석 버전</dt>
        <dd>{a.version}</dd>
      </dl>
    </div>
  );
}
