import type { TeamNews, TeamNewsSide } from "@edge/contracts";

import { positionLabel, reasonLabel, sideSummary } from "@/lib/teamNews";

import { LocalTime } from "./LocalTime";

function Side({ side, tz }: { side: TeamNewsSide; tz: string }) {
  const starters = side.starters ?? [];
  const absences = side.absences ?? [];
  return (
    <div className="card team-news-side">
      <h3>
        {side.team_name}
        {side.formation && <span className="muted small"> · {side.formation}</span>}
      </h3>
      <p className="small">{sideSummary(side)}</p>
      {starters.length > 0 && (
        <ol className="lineup">
          {starters.map((p) => (
            <li key={p.player_id} className={p.regular ? undefined : "not-regular"}>
              <span className="lineup-no">{p.number ?? ""}</span>
              <span>{p.name}</span>
              <span className="muted small">{positionLabel(p.position)}</span>
              {!p.regular && side.regulars_known && <span className="lineup-tag">로테이션</span>}
            </li>
          ))}
        </ol>
      )}
      {absences.length > 0 && (
        <>
          <h4>결장·출전 불투명</h4>
          <ul className="absences">
            {absences.map((a) => (
              <li key={a.player_id}>
                {a.name}
                <span className="muted small">
                  {" "}
                  {a.status === "out" ? "결장" : "불투명"}
                  {a.reason && ` · ${reasonLabel(a.reason)}`}
                  {a.regular && " · 주전"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="muted small" style={{ margin: "6px 0 0" }}>
        {side.lineup_captured_at && (
          <>
            명단 확인 <LocalTime iso={side.lineup_captured_at} fallbackTz={tz} />
            {" · "}
          </>
        )}
        {side.absences_captured_at && (
          <>
            결장 정보 <LocalTime iso={side.absences_captured_at} fallbackTz={tz} />
            {" · "}
          </>
        )}
        주전 판단: 최근 {side.recent_matches}경기 출전 시간
      </p>
    </div>
  );
}

/** Line-ups and absences (reference only; the model does not use them yet). */
export function TeamNewsSection({ news, tz }: { news: TeamNews; tz: string }) {
  return (
    <section aria-labelledby="team-news-title">
      <h2 id="team-news-title">
        {news.lineups_announced ? "선발 명단" : "결장 선수"}
        {news.lineups_announced && <span className="badge">발표됨</span>}
      </h2>
      <div className="grid-2">
        <Side side={news.home} tz={tz} />
        <Side side={news.away} tz={tz} />
      </div>
      <p className="muted small">
        {news.note} 선발 명단은 보통 경기 약 1시간 전에 발표돼요. 시장(배당)은 명단이 나오면 빠르게
        움직이니, 분석과 시장의 차이가 클 때 명단을 함께 확인해 보세요.
      </p>
    </section>
  );
}
