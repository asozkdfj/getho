"use client";

import { OUTCOMES, type FixtureSummary } from "@edge/contracts";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { OUTCOME_LABEL, pct } from "@/lib/format";
import {
  EMPTY_FORM,
  createBody,
  newRequestKey,
  revisionBody,
  type PickFormValues,
} from "@/lib/personalPicks";
import { formatInTz } from "@/lib/time";

import { LeagueMark } from "./LeagueMark";
import { MatchPicker } from "./MatchPicker";

const PROB_KEY = { HOME: "home", DRAW: "draw", AWAY: "away" } as const;

type Mode =
  | { kind: "create"; fixtures: FixtureSummary[] }
  | { kind: "revise"; pickId: string; baseRevision: number; initial: PickFormValues };

/**
 * Records a pick (or a new revision of one). The request key is made once per
 * draft, so a retry after a network error cannot store the pick twice.
 */
export function PersonalPickForm({ mode, tz }: { mode: Mode; tz: string }) {
  const router = useRouter();
  const [values, setValues] = useState<PickFormValues>(
    mode.kind === "revise" ? mode.initial : EMPTY_FORM,
  );
  const [fixtureId, setFixtureId] = useState<number | null>(null);
  const [key, setKey] = useState(() => newRequestKey());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<PickFormValues>) => setValues((v) => ({ ...v, ...patch }));

  const chosen =
    mode.kind === "create" ? (mode.fixtures.find((f) => f.id === fixtureId) ?? null) : null;
  const started = chosen !== null && chosen.status !== "scheduled";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    let url: string;
    let built;
    if (mode.kind === "create") {
      if (fixtureId === null) {
        setError("경기를 고르세요.");
        return;
      }
      url = "/api/personal-picks";
      built = createBody(fixtureId, key, values, tz);
    } else {
      url = `/api/personal-picks/${mode.pickId}/revisions`;
      built = revisionBody(mode.baseRevision, key, values, tz);
    }
    if (built.error !== null) {
      setError(built.error);
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(built.body),
      });
      const data = (await res.json().catch(() => ({}))) as { pick_id?: string; detail?: unknown };
      if (!res.ok) {
        setError(
          typeof data.detail === "string" ? data.detail : `저장하지 못했어요 (${res.status}).`,
        );
        return;
      }
      setKey(newRequestKey()); // the next change is a new request
      if (mode.kind === "create" && data.pick_id) router.push(`/my-picks/${data.pick_id}`);
      else router.refresh();
    } catch {
      setError("연결이 끊겼어요. 다시 저장하면 같은 요청으로 한 번만 저장돼요.");
    } finally {
      setSaving(false);
    }
  }

  if (mode.kind === "create" && chosen === null) {
    return (
      <div className="card stack pick-form">
        <div className="field">
          <span>경기와 내 선택 (정규시간 승무패)</span>
          <span className="muted small">
            경기 줄에서 홈승·무·원정승을 누르세요. 버튼 아래 숫자는 모델 확률이에요.
          </span>
        </div>
        <MatchPicker
          fixtures={mode.fixtures}
          tz={tz}
          value={null}
          onChange={(c) => {
            setFixtureId(c.fixtureId);
            set({ selection: c.selection });
          }}
        />
      </div>
    );
  }

  return (
    <form className="card stack pick-form" onSubmit={submit}>
      {chosen && (
        <div className="chosen-match">
          <div className="chosen-match-info">
            <span className="muted small">
              <LeagueMark league={chosen.league} size={16} /> {chosen.league.country_ko} ·{" "}
              {chosen.league.name} · {formatInTz(chosen.kickoff_at, tz, "datetime")}
            </span>
            <strong>
              {chosen.home_team.name} <span className="muted">(홈) vs</span> {chosen.away_team.name}{" "}
              <span className="muted">(원정)</span>
            </strong>
          </div>
          <button
            type="button"
            className="btn secondary chosen-match-change"
            onClick={() => setFixtureId(null)}
          >
            다른 경기
          </button>
        </div>
      )}
      {started && (
        <p className="muted small" style={{ margin: 0 }}>
          이미 시작한 경기예요. 사후 입력으로 저장되고, 경기 전 결정 시각이 필요해요.
        </p>
      )}

      <fieldset className="field">
        <legend>내 선택 (정규시간 승무패)</legend>
        <div className="pick-buttons">
          {OUTCOMES.map((o) => (
            <button
              key={o}
              type="button"
              aria-pressed={values.selection === o}
              onClick={() => set({ selection: o })}
            >
              <strong>{OUTCOME_LABEL[o]}</strong>
              {chosen?.model_probabilities && (
                <small>모델 {pct(chosen.model_probabilities[PROB_KEY[o]], 0)}</small>
              )}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="field">
        <legend>결정 시각</legend>
        <label className="inline">
          <input
            type="checkbox"
            checked={values.decidedNow}
            onChange={(e) => set({ decidedNow: e.target.checked })}
          />{" "}
          지금 결정 (서버 시각으로 기록)
        </label>
        {!values.decidedNow && (
          <label className="inline">
            <input
              type="datetime-local"
              value={values.decisionLocal}
              onChange={(e) => set({ decisionLocal: e.target.value })}
            />{" "}
            <span className="muted small">{tz} 기준 · 경기 시작 전이어야 해요</span>
          </label>
        )}
      </fieldset>

      <div className="grid-2">
        <label className="field">
          <span>받은 배당 (선택)</span>
          <input
            inputMode="decimal"
            placeholder="예: 2.35"
            value={values.entryOdds}
            onChange={(e) => set({ entryOdds: e.target.value })}
          />
        </label>
        <label className="field">
          <span>금액 원 (선택)</span>
          <input
            inputMode="numeric"
            placeholder="비워 둬도 분석돼요"
            value={values.stakeKrw}
            onChange={(e) => set({ stakeKrw: e.target.value })}
          />
        </label>
        <label className="field">
          <span>내 예상 확률 % (선택)</span>
          <input
            inputMode="decimal"
            placeholder="예: 45"
            value={values.userProbabilityPct}
            onChange={(e) => set({ userProbabilityPct: e.target.value })}
          />
        </label>
      </div>
      <label className="field">
        <span>선택 이유 (선택, 500자)</span>
        <textarea
          rows={3}
          maxLength={500}
          value={values.reason}
          onChange={(e) => set({ reason: e.target.value })}
        />
      </label>
      <label className="inline">
        <input
          type="checkbox"
          checked={values.purchased}
          onChange={(e) => set({ purchased: e.target.checked })}
        />{" "}
        실제로 구매했어요 (내 기록일 뿐, 서비스가 확인하거나 구매하지 않아요)
      </label>

      {error && (
        <p className="error small" role="alert" style={{ margin: 0 }}>
          {error}
        </p>
      )}
      <div>
        <button className="btn" type="submit" disabled={saving}>
          {saving ? "저장 중…" : mode.kind === "create" ? "기록하기" : "수정본 저장"}
        </button>
      </div>
    </form>
  );
}
