# 확률 구간 표시 · 자동 조합 (2026-10-16)

사용자 요청: (1) 맞추기 쉬운 경기를 색으로 은은하게 구분, (2) 경기 수를 정하면 모두 맞을 확률이 가장 높은 조합을
추천. "배당 5배 이상 중 가장 확률 높은 조합" 같은 조건부 추천은 보완 장치와 함께 다음 단계로 미뤘습니다(사용자 결정).

## 구현

| 기능 | 규칙 | 위치 |
| --- | --- | --- |
| 확률 구간 | 가장 높은 결과의 분석 확률 ≥ 65% "확률 높음", 55~65% "확률 다소 높음". 예정 경기 + 검증 리그만(데모는 전체) | `apps/web/lib/confidence.ts`, 경기 카드 왼쪽 파란 테두리·작은 태그, 범례 |
| 자동 조합 | 선택 가능한 검증 리그 경기(데모는 전체)의 가장 높은 결과를 골라 확률 곱이 최대인 2~3경기. 같은 팀 중복 금지, 동률은 이른 킥오프 | `apps/web/lib/autoCombo.ts`, 조합 화면 "자동 조합" (리그를 고르면 그 리그 안에서) |

- 색은 파란색(강조색)입니다. 초록은 이미 "분석과 시장의 차이"와 주목할 경기 카드 테두리에 쓰고 있어 피했습니다.
- 자동 조합은 고른 뒤 기존 조합 분석 API로 바로 계산합니다(시장 확률, 배당, 기대값이 함께 나옴).
- 배당은 수집한 북메이커(운영 기본 Bet365) 기준이며 국내 배당은 보통 더 낮다는 안내를 붙였습니다.
  베트맨 배당 직접 입력은 하지 않습니다(사용자 결정: 번거로움, 조건 없는 추천에는 필요 없음).

## 근거: 과거 3시즌 시뮬레이션 (검토용)

입력: 시장 기준선 실험(PR #7)의 경기별 운영 모델 확률·시장 확률(`ml/reports/backtest-market.predictions.jsonl.gz`,
주 단위 재학습·결과 3시간 지연)과 Bet365 1X2 배당, 9개 리그. 아래 스크립트로 재현합니다.

**확률 구간** — 가장 높은 결과의 분석 확률별 실제 적중

| 구간 | 검증 2020-23 비중 · 평균 확률 · 적중 | 후속 2023-26 비중 · 평균 확률 · 적중 |
| --- | --- | --- |
| 65% 이상 | 11.5% · 71.6% · **75.6%** | 11.8% · 72.1% · **76.8%** |
| 55~65% | 17.9% · 59.5% · **61.5%** | 18.7% · 59.5% · **60.9%** |
| 45~55% | 32.4% · 49.6% · 48.8% | 33.1% · 49.6% · 49.0% |
| 45% 미만 | 38.2% · 40.6% · 40.6% | 36.4% · 40.7% · 39.9% |

확률이 실제 적중과 잘 맞고, 높은 구간은 오히려 조금 보수적입니다. 단, 시장의 1순위도 이 경기들을 똑같이 맞힙니다
(65% 이상 구간 76.8% vs 76.8%). 구간은 "결과가 비교적 뻔한 경기"를 뜻하며, 화면 문구도 그렇게 썼습니다.

**자동 조합** — KST 하루(09시→다음 날 09시)마다 추천했다고 가정

| 후속 2023-26, 554일 | 분석 확률 | 시장 확률 | 실제 적중 | 평균 배당 | 수익률 |
| --- | --- | --- | --- | --- | --- |
| 3경기, 가장 확률 높은 조합 (이번 구현) | 27.2% | 28.6% | **33.2%** | 4.24 | −1.7% |
| 3경기, 배당 ≥ 5 중 가장 확률 높은 조합 (보류) | 19.0% | 14.4% | **15.3%** | 6.30 | −9.5% |

- 조건 없는 추천은 분석 확률이 실제보다 낮게 나올 만큼 정직합니다(검증 구간도 26.1% → 30.7%).
- 배당 조건을 붙이면 분석이 시장보다 낙관하는 경기만 골라져 확률이 부풀려집니다(19.0% vs 실제 15.3%). 그래서
  조건부 추천은 시장 확률과 과거 실적을 함께 보여 주는 보완 장치가 생길 때까지 넣지 않습니다(TODO #37).
- 계산 시간을 줄이려고 하루 중 분석 확률 상위 40경기 안에서만 조합을 찾았습니다(조건부 추천 수치에 영향 가능).

## 하지 않은 것 / 한계

- 다른 시간대 브라우저, 실데이터 화면은 확인하지 않았습니다. 데모 데이터에서 데스크톱·모바일·다크 모드를 확인했습니다.
- 구간 수치는 9개 리그 합산이며, 검증 리그 목록이 바뀌면 다시 재야 합니다.

## 부록: 시뮬레이션 스크립트

```python
"""Feasibility review (not committed): confidence tiers and a constrained combo recommender."""
import gzip, json, itertools, math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
from edge_ingestion.history import club_match_data as cmd

CACHE = Path(".cache/history")
rows = [json.loads(l) for l in gzip.open("ml/reports/backtest-market.predictions.jsonl.gz", "rt")]
odds = {}
for code in "en.1,en.2,de.1,de.2,es.1,it.1,fr.1,nl.1,pt.1".split(","):
    ms, _ = cmd.load(code, "2018-19", "2025-26", CACHE)
    for m in ms:
        if m.odds:
            odds[(m.result.kickoff_at.isoformat(), m.result.home, m.result.away)] = m.odds
VAL = {"2020-21", "2021-22", "2022-23"}; FU = {"2023-24", "2024-25", "2025-26"}
for r in rows:
    r["odds"] = odds.get((r["kickoff_at"], r["home"], r["away"]))
rows = [r for r in rows if r["odds"]]
print("rows with odds", len(rows))

# 1) confidence tiers by the model's top outcome probability
print("\n== tiers (model top-outcome probability)")
edges = [0, 0.45, 0.55, 0.65, 1.01]
for name, seasons in (("validation", VAL), ("follow-up", FU)):
    sub = [r for r in rows if r["season"] in seasons]
    print(name, len(sub))
    for lo, hi in zip(edges, edges[1:]):
        t = [r for r in sub if lo <= max(r["production"]) < hi]
        if not t: continue
        hit = np.mean([int(np.argmax(r["production"]) == r["outcome"]) for r in t])
        mp = np.mean([max(r["production"]) for r in t])
        mk = np.mean([int(np.argmax(r["market_only"]) == r["outcome"]) for r in t])
        print(f"  [{lo:.2f},{hi:.2f}) share {len(t)/len(sub):5.1%} n {len(t):5d}  mean prob {mp:.3f}  hit {hit:.3f}  (market's top pick hit {mk:.3f})")

# 2) combo recommender per KST pick day (09:00 -> 09:00)
KST = ZoneInfo("Asia/Seoul")
days = defaultdict(list)
for r in rows:
    k = datetime.fromisoformat(r["kickoff_at"]).astimezone(KST) - timedelta(hours=9)
    days[k.date()].append(r)

def best_combo(ms, probs_key, k, min_odds, max_odds=None):
    n = len(ms)
    if n < k: return None
    P = np.array([m[probs_key] for m in ms]); O = np.array([m["odds"] for m in ms])
    best = None
    for idx in itertools.combinations(range(n), k):
        p = P[list(idx)]; o = O[list(idx)]
        # all 3^k outcome choices
        lp = np.log(p); lo = np.log(o)
        grids_p = sum(np.ix_(*[lp[i] for i in range(k)]))
        grids_o = sum(np.ix_(*[lo[i] for i in range(k)]))
        ok = grids_o >= math.log(min_odds) - 1e-12
        if max_odds: ok &= grids_o <= math.log(max_odds)
        if not ok.any(): continue
        cand = np.where(ok, grids_p, -np.inf)
        j = np.unravel_index(np.argmax(cand), cand.shape)
        if best is None or cand[j] > best[0]:
            best = (cand[j], idx, j, grids_o[j])
    if best is None: return None
    _, idx, j, lo_ = best
    legs = [(ms[i], j[t]) for t, i in enumerate(idx)]
    hit = all(m["outcome"] == o for m, o in legs)
    model_p = math.prod(m["production"][o] for m, o in legs)
    market_p = math.prod(m["market_only"][o] for m, o in legs)
    return dict(hit=hit, odds=math.exp(lo_), model_p=model_p, market_p=market_p)

def run(name, seasons, probs_key, k, min_odds, max_odds=None, top=40):
    res = []
    for d, ms in sorted(days.items()):
        ms = [m for m in ms if m["season"] in seasons]
        if len(ms) < k: continue
        # keep the search bounded: the matches with the most confident model outcome
        ms = sorted(ms, key=lambda m: -max(m[probs_key]))[:top]
        c = best_combo(ms, probs_key, k, min_odds, max_odds)
        if c: res.append(c)
    n = len(res); hits = sum(c["hit"] for c in res)
    ret = np.array([(c["odds"] - 1) if c["hit"] else -1.0 for c in res])
    print(f"  {name:48s} days {n:4d} claimed(model) {np.mean([c['model_p'] for c in res]):.3f} "
          f"market says {np.mean([c['market_p'] for c in res]):.3f} actual hit {hits/n:.3f}  "
          f"mean odds {np.mean([c['odds'] for c in res]):5.2f}  return {ret.mean():+.3f}")

for label, seasons in (("validation 2020-23", VAL), ("follow-up 2023-26", FU)):
    print("\n==", label)
    run("3 legs, highest model prob (no odds limit)", seasons, "production", 3, 1.0)
    run("3 legs, odds >= 5, highest model prob", seasons, "production", 3, 5.0)
    run("3 legs, odds >= 5, highest MARKET prob (ref)", seasons, "market_only", 3, 5.0)
    run("2 legs, odds >= 3, highest model prob", seasons, "production", 2, 3.0)
```
