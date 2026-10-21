import type { PersonalPickRevision } from "@edge/contracts";

import { OUTCOME_LABEL, odds, pct } from "@/lib/format";
import { SOURCE_LABEL } from "@/lib/personalPicks";

import { LocalTime } from "./LocalTime";

/** What the user entered for one revision; free text is rendered as text (escaped). */
export function PickInputs({ r, tz }: { r: PersonalPickRevision; tz: string }) {
  return (
    <dl className="kv small">
      <dt>선택</dt>
      <dd>{OUTCOME_LABEL[r.selection]}</dd>
      <dt>결정 시각</dt>
      <dd>
        <LocalTime iso={r.decision_at} fallbackTz={tz} format="full" />
        {r.time_evidence === "user_stated" ? " (직접 입력)" : " (서버 시각)"}
      </dd>
      <dt>저장 시각</dt>
      <dd>
        <LocalTime iso={r.recorded_at} fallbackTz={tz} format="full" />
      </dd>
      <dt>기록 유형</dt>
      <dd>{SOURCE_LABEL[r.source_type]}</dd>
      <dt>받은 배당</dt>
      <dd>{r.entry_odds === null ? "미입력" : odds(r.entry_odds)}</dd>
      <dt>금액</dt>
      <dd>{r.stake_krw === null ? "미입력" : `${r.stake_krw.toLocaleString("ko-KR")}원`}</dd>
      <dt>내 예상 확률</dt>
      <dd>{r.user_probability === null ? "미입력" : pct(r.user_probability)}</dd>
      <dt>구매</dt>
      <dd>{r.self_reported_purchase ? "구매했다고 기록 (미확인)" : "기록 없음"}</dd>
      <dt>이유</dt>
      <dd style={{ whiteSpace: "pre-wrap" }}>{r.user_reason ?? "미입력"}</dd>
    </dl>
  );
}
