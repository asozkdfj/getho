import type { HighlightList } from "@edge/contracts";
import Link from "next/link";

import {
  caveatText,
  highlightSentence,
  outcomeName,
  sharedCaveatText,
  sharedCaveats,
} from "@/lib/highlights";
import { leagueLabel } from "@/lib/leagues";

import { LocalTime } from "./LocalTime";

export function Highlights({
  data,
  tz,
  title = "이번 주 주목할 경기",
  showLeague = true,
}: {
  /** null = the request failed (the rest of the page still renders) */
  data: HighlightList | null;
  tz: string;
  title?: string;
  /** Off on a league page, where every card is the same league. */
  showLeague?: boolean;
}) {
  if (data === null) {
    return (
      <section className="highlights" aria-labelledby="highlights-title">
        <h2 id="highlights-title">{title}</h2>
        <p className="card small error">
          주목할 경기를 불러오지 못했어요. 잠시 후 새로고침해 주세요.
        </p>
      </section>
    );
  }
  const shared = sharedCaveats(data.items);
  return (
    <section className="highlights" aria-labelledby="highlights-title">
      <h2 id="highlights-title">{title}</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {data.note} <Link href="/guide#gap">왜 차이가 날까요?</Link>
      </p>
      {shared.length > 0 && (
        <ul className="caveats">
          {shared.map((c) => (
            <li key={c}>⚠ {sharedCaveatText(c)}</li>
          ))}
        </ul>
      )}
      {data.items.length === 0 ? (
        <p className="card small">
          지금 보여 드릴 주목할 경기가 없어요. 분석이 있는 예정 경기가 없거나, 분석과 시장의 차이가
          표시 기준에 못 미친 경우예요.
        </p>
      ) : (
        <div className="grid-2">
          {data.items.map((h) => (
            <Link
              key={h.fixture.id}
              href={`/fixtures/${h.fixture.id}`}
              className="card highlight-card"
            >
              <div className="fixture-meta">
                <LocalTime iso={h.fixture.kickoff_at} fallbackTz={tz} />
                <span className="positive small">+{Math.round(h.edge * 100)}%p</span>
              </div>
              {showLeague && <div className="muted small">{leagueLabel(h.fixture.league)}</div>}
              <div className="highlight-teams">
                {h.fixture.home_team.name} <span className="muted">vs</span>{" "}
                {h.fixture.away_team.name}
              </div>
              <div className="highlight-pick">{outcomeName(h)}</div>
              <p className="small" style={{ margin: "4px 0 0" }}>
                {highlightSentence(h)}
              </p>
              {h.caveats.some((c) => !shared.includes(c)) && (
                <ul className="caveats">
                  {h.caveats
                    .filter((c) => !shared.includes(c))
                    .map((c) => (
                      <li key={c}>⚠ {caveatText(c, h)}</li>
                    ))}
                </ul>
              )}
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
