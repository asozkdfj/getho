import type { DataStatus } from "@edge/contracts";

import { LocalTime } from "./LocalTime";

/** Data freshness at a glance; stale data is called out instead of hidden. */
export function DataStatusBadge({ status, tz }: { status: DataStatus | null; tz: string }) {
  if (status === null) {
    return <p className="data-status stale small">데이터 상태를 확인하지 못했어요.</p>;
  }
  const ok = status.status === "ok";
  return (
    <p className={`data-status small ${ok ? "ok" : "stale"}`}>
      <span aria-hidden>{ok ? "●" : "▲"}</span> {ok ? "데이터 최신" : "데이터가 오래됐어요"}
      {status.last_success_at && (
        <>
          {" "}
          · 마지막 수집 <LocalTime iso={status.last_success_at} fallbackTz={tz} />
        </>
      )}
      {!status.last_success_at && " · 아직 수집 기록 없음"}
      {!ok && " · 오래된 데이터로는 오늘의 픽을 고르지 않아요"}
    </p>
  );
}
