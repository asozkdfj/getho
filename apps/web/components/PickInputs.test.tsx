import type { PersonalPickRevision } from "@edge/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PickInputs } from "./PickInputs";

const revision = {
  revision: 1,
  recorded_at: "2026-10-21T10:00:00Z",
  decision_at: "2026-10-21T10:00:00Z",
  time_evidence: "server_clock",
  source_type: "prospective_record",
  selection: "AWAY",
  entry_odds: null,
  stake_krw: null,
  user_probability: null,
  user_reason: '<img src=x onerror="alert(1)"> 홈 수비 불안',
  self_reported_purchase: false,
} as unknown as PersonalPickRevision;

describe("PickInputs", () => {
  it("renders the reason as text, never as markup", () => {
    const html = renderToStaticMarkup(<PickInputs r={revision} tz="Asia/Seoul" />);
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt; 홈 수비 불안");
  });

  it("shows missing inputs as not entered instead of zero", () => {
    const html = renderToStaticMarkup(<PickInputs r={revision} tz="Asia/Seoul" />);
    expect(html.match(/미입력/g)?.length).toBe(3); // odds, stake, own probability
    expect(html).not.toMatch(/0원/);
    expect(html).toContain("경기 전 기록");
  });
});
