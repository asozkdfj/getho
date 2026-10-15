import type { HighlightList } from "@edge/contracts";
import Link from "next/link";

import { caveatText, highlightSentence, outcomeName } from "@/lib/highlights";

import { LocalTime } from "./LocalTime";

export function Highlights({ data, tz }: { data: HighlightList; tz: string }) {
  return (
    <section className="highlights" aria-labelledby="highlights-title">
      <h2 id="highlights-title">이번 주 주목할 경기</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        {data.note} <Link href="/guide#gap">왜 차이가 날까요?</Link>
      </p>
      {data.items.length === 0 ? (
        <p className="card small">
          이번 주에는 분석과 시장의 생각이 크게 다른 경기가 없어요. 둘의 시각이 비슷하다는 뜻이에요.
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
              <div className="highlight-teams">
                {h.fixture.home_team.name} <span className="muted">vs</span>{" "}
                {h.fixture.away_team.name}
              </div>
              <div className="highlight-pick">{outcomeName(h)}</div>
              <p className="small" style={{ margin: "4px 0 0" }}>
                {highlightSentence(h)}
              </p>
              {h.caveats.length > 0 && (
                <ul className="caveats">
                  {h.caveats.map((c) => (
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
