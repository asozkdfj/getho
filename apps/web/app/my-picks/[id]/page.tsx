import type { PersonalPickRevision } from "@edge/contracts";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { LocalTime } from "@/components/LocalTime";
import { PersonalPickForm } from "@/components/PersonalPickForm";
import { PickAnalysisView } from "@/components/PickAnalysisView";
import { PickInputs } from "@/components/PickInputs";
import { fetchPersonalPick } from "@/lib/api";
import { DEFAULT_TZ } from "@/lib/config";
import { OUTCOME_LABEL, statusLabel } from "@/lib/format";
import { EMPTY_FORM, SOURCE_LABEL, type PickFormValues } from "@/lib/personalPicks";
import { PICK_ID } from "@/lib/proxy";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "내 픽" };

function formValues(r: PersonalPickRevision): PickFormValues {
  return {
    ...EMPTY_FORM,
    selection: r.selection,
    entryOdds: r.entry_odds === null ? "" : r.entry_odds.toFixed(2),
    stakeKrw: r.stake_krw === null ? "" : String(r.stake_krw),
    userProbabilityPct:
      r.user_probability === null ? "" : String(Math.round(r.user_probability * 1000) / 10),
    reason: r.user_reason ?? "",
    purchased: r.self_reported_purchase,
  };
}

export default async function MyPickPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!PICK_ID.test(id)) notFound();
  const pick = await fetchPersonalPick(id);
  if (!pick) notFound();
  const tz = DEFAULT_TZ;
  const cur = pick.current;
  const started = pick.status !== "scheduled";

  return (
    <>
      <div className="page-head">
        <div>
          <p className="muted small" style={{ margin: 0 }}>
            <Link href="/my-picks">← 내 픽 기록</Link>
          </p>
          <h1>
            {pick.home_team.name} vs {pick.away_team.name}
          </h1>
          <p className="muted small" style={{ margin: 0 }}>
            {pick.league.country_ko} · {pick.league.name} ·{" "}
            <LocalTime iso={pick.kickoff_at} fallbackTz={tz} format="full" /> ·{" "}
            {statusLabel(pick.status)}
            {pick.home_score !== null &&
              pick.away_score !== null &&
              ` ${pick.home_score}:${pick.away_score}`}
          </p>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat">
          <div className="label">내 선택</div>
          <div className="value">{OUTCOME_LABEL[cur.selection]}</div>
        </div>
        <div className="stat">
          <div className="label">당시 모델 1순위</div>
          <div className="value">
            {cur.analysis.model ? OUTCOME_LABEL[cur.analysis.model.top_outcome] : "없음"}
          </div>
        </div>
        <div className="stat">
          <div className="label">기록 유형</div>
          <div className="value small-value">{SOURCE_LABEL[cur.source_type]}</div>
          {pick.edited_after_kickoff && (
            <div className="muted small">경기 전 기록은 {pick.prospective_revision}번 수정본</div>
          )}
        </div>
        <div className="stat">
          <div className="label">수정본</div>
          <div className="value">{pick.revisions}</div>
        </div>
      </div>

      {pick.status === "finished" && (
        <p className="muted small">
          경기 결과와 당시 판단을 나란히 보는 사후 복기는 다음 단계(R2)에서 추가돼요. 지금은 당시
          위험만 보여 줘요.
        </p>
      )}

      <section className="card stack" style={{ marginTop: 16 }}>
        <h2 style={{ margin: 0 }}>당시 위험 (수정본 {cur.revision})</h2>
        <PickAnalysisView a={cur.analysis} tz={tz} />
      </section>

      <section className="card stack" style={{ marginTop: 16 }}>
        <h2 style={{ margin: 0 }}>내가 입력한 내용</h2>
        <PickInputs tz={tz} r={cur} />
      </section>

      {pick.history.length > 1 && (
        <section className="stack" style={{ marginTop: 16 }}>
          <h2 style={{ margin: 0 }}>수정 이력</h2>
          {pick.history
            .slice(0, -1)
            .reverse()
            .map((r) => (
              <details key={r.revision} className="card">
                <summary>
                  수정본 {r.revision} · {OUTCOME_LABEL[r.selection]} · {SOURCE_LABEL[r.source_type]}
                </summary>
                <PickInputs tz={tz} r={r} />
                <PickAnalysisView a={r.analysis} tz={tz} />
              </details>
            ))}
        </section>
      )}

      <section className="stack" style={{ marginTop: 16 }}>
        <h2 style={{ margin: 0 }}>수정하기</h2>
        <p className="muted small" style={{ margin: 0 }}>
          수정은 새 수정본으로 저장되고 이전 기록은 그대로 남아요.
          {started && " 경기 시작 후 저장하는 수정본은 사후 입력으로 표시돼요."}
        </p>
        <PersonalPickForm
          mode={{
            kind: "revise",
            pickId: pick.pick_id,
            baseRevision: cur.revision,
            initial: formValues(cur),
          }}
          tz={tz}
        />
      </section>
    </>
  );
}
