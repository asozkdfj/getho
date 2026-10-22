# 2026-10-22 독립 QA 및 모델 개선 검토

작성: Codex. 최종 판정: **NEEDS_CHANGES**. 운영 모델 변경·main merge·배포 없음.

## 대상과 환경

- 실행 main: `715404d3e7e83094f6bb7c7892c230d07ce103e3`.
- 직전 QA main: `3f7a546bd6519df66063d2f11163e3a40f2e8965`. 과거 판정을 그대로 적용하지 않고 변경 범위를 재검증했다.
- 실행 checkout: `getho-latest-qa`, `codex/qa-overnight-2026-10-20` (origin/main fast-forward).
- 기록 checkout: `getho-independent-qa`, `codex/main-ui-independent-qa`. Claude 기능 코드 수정 없음.
- Windows PowerShell, 기존 QA Python venv, Node/Next.js 16.4.1, 격리 PostgreSQL `127.0.0.1:15432/edge_test_morning`.
- DB 테스트는 Mock 수집 데이터 사용. API-Football 실연동 검증이 아니다.

| PR | Base SHA | Head SHA |
| --- | --- | --- |
| #37 | `797b3c4dcc8ee7f01789bb5fc81c62b9acfc13ba` | `ebbb5a644d34af30e5a6cefbd5c534d81ab3a849` |
| #38 | `3c0f7493bc24b80dba61f67762dc33516f4dd5dc` | `7d636d9f2b51a6cf8cca21c526b65026d24b18ca` |
| #39 | `d390bd23d998e641536a3a802a9b5770c533baf9` | `bb5a533917fe79a08ddb09fc37dc8268cb6f8252` |
| #40 | `7c1cef9eadec05c7b982b409af3dd240534f74f4` | `2376737da377e04904aaa04fa513882e7be1ef64` |

검토 범위: 리그 선정 보정, 베트맨 as-of/테마 수정, 개인 픽 R1, 선수 가용성 readiness 및 실험 초안.
위 PR은 조회 시 모두 merge 완료. 실행 결과는 통합 main SHA 기준이며 각 PR 단독 checkout 테스트는 아니다.

## 실제 실행

| 검사 | 결과 |
| --- | --- |
| 아래 Python 변경 범위 및 이전 Betman 반례 | **58 PASS** |
| 독립 신규 경계 조건 2개 | **2 FAIL**, 두 번 재현 |
| `npm test` | **122 PASS**, 25 files |
| `npm run typecheck`, `npm run lint`, `npm run build` | **PASS** |
| 변경 Python 서비스/worker 및 관련 테스트 Ruff | **PASS** |
| Alembic | 테스트 fixture에서 base까지 downgrade, 0012까지 upgrade 성공. 별도 autogenerate check는 미실행 |
| 테마 독립 Node VM 재현 | **PASS**: cross-tab dark/dark, 저장 차단 light/light 및 next=dark |

Python 실행 (저장소 루트, PYTHONPATH에 apps/api, ml, workers/ingestion; TEST_DATABASE_URL에 위 격리 DB; REQUIRE_DB_TESTS=1):

```text
python -m pytest -q --tb=short tests/integration/test_personal_picks.py tests/integration/test_availability_readiness.py tests/integration/test_betman.py tests/integration/test_codex_betman_asof.py workers/ingestion/tests/test_league_verification.py
python -m pytest -q --tb=line tests/integration/test_codex_oct22.py
python -m ruff check apps/api/edge_api/services/personal_picks.py workers/ingestion/edge_ingestion/availability_readiness.py workers/ingestion/edge_ingestion/league_verification.py tests/integration/test_personal_picks.py tests/integration/test_availability_readiness.py
```

새 재현 파일: `scripts/qa/test_oct22_regressions.py`. 대상 SHA checkout의 `tests/integration/test_codex_oct22.py`로 복사해 실행한다. 해당 SHA의 기존 테스트 helper와 fixture에 의존한다.
테마 재현은 기존 `scripts/qa/reproduce_theme.cjs` VM DOM stub에 `getAttribute`를 제공해 최신 구현에 맞췄다. 처음 잘못 지정한 스크립트 상대 경로는 절대 경로로 수정해 성공했다. 게시 checkout의 import 정렬 차이도 Ruff로 수정했다. 이 실행 환경 문제들은 제품 결함으로 집계하지 않았다.

미실행: Python 전체 suite, 실제 브라우저 수동 UI, 실제 API-Football 요청, 운영 DB readiness, 별도 API 계약 생성 비교, Docker 전체 smoke, 원본 ML 학습/백테스트. 따라서 모든 UI 8건·운영 데이터·모델 정확도가 이번에 전부 검증됐다는 의미는 아니다.

## 이전 지적 재검증

- **PASS — Betman 매핑 시점**: `test_codex_betman_asof.py` 포함 통과. 과거 분석에 뒤늦은 매핑이 끼는 기존 반례 해결.
- **PASS — 테마 두 결함**: 다른 탭 변경과 localStorage 차단 상황에서 표시/상태 일치 재현.
- **PASS — #37 선정 기준 반영**: 90% coverage 조건 테스트 통과. 저장 보고서가 대상 8개/통과 6개와 탐색 결과를 구분한다. 이번에는 원본 리그 재학습을 하지 않았다.

## 신규 발견

### [P2] PICK-STATE-1 — 종료 경기도 사전 기록으로 저장될 수 있음

- 위치: `apps/api/edge_api/services/personal_picks.py:258` 및 `:339`.
- 재현: 미래 kickoff를 가진 테스트 경기의 status를 finished, score를 1–0으로 설정하고 현재 시각으로 POST `/personal-picks`.
- 실제: HTTP 200, status=finished, `source_type=prospective_record`, `prospective_revision=1`.
- 기대: 상태와 일정이 모순되면 신뢰 가능한 사전 기록으로 인정하지 않아야 한다. 입력을 거절하거나 별도 검증 불가/회고 기록으로 표시한다.
- 영향: 일정 정정·잘못된 공급 데이터 같은 모순 상황에서 향후 사전 기록 성과 집계가 오염될 수 있다. **합성 경계 조건에서 재현했으며 실제 운영에 이런 행이 있음을 확인한 것은 아니다.**
- 수정: kickoff 외 상태/결과 및 필요시 FixtureObservation을 확인하고 사전성 판단 근거를 동결한다. 과거 경기 회고 입력 자체는 유지한다.
- 재검증: finished/live/cancelled 및 일정 정정, 과거 회고, 정상 예정 경기, revision/idempotency 회귀 테스트.

### [P2] AVAIL-TIME-1 — 실제 사용 가능 시각보다 lead time이 길게 계산됨

- 위치: `workers/ingestion/edge_ingestion/availability_readiness.py:73–100`.
- 재현: 양 팀 정보 captured_at=킥오프 30시간 전, DB created_at=1시간 전.
- 실제: `_lead_hours`가 **30시간** 반환. 기대: 실제 시스템 가용 시점 기준 **1시간**.
- 원인: 두 시각 모두 kickoff 전인지만 필터하고 `min(captured_at)`로 집계한다. 지연 저장된 데이터가 실제보다 일찍 사용 가능했던 것으로 보인다.
- 수정: snapshot별 `max(captured_at, created_at)` 후 팀별 최초 가용 시각을 집계하고, 양 팀 중 늦은 시각을 사용한다.
- 재검증: 지연 저장, kickoff 이후 저장, 여러 snapshot 순서 역전 및 동률.
- 영향: 실험 준비 상태 보고서의 데이터 가용성 판단. 현재 운영 모델 예측이 바뀌었다는 증거는 없다.

## QA 후 모델 성능 향상 검토

이번 PR은 후보 성능 제출이 아니라 준비 단계다. 새 후보의 LL/Brier/accuracy, 표본 수, 평가 구간, CI는 **미산출**이며 모델 채택은 **판단 불가**다. 테스트 통과를 정확도 개선으로 해석하지 않는다.

우선 검토할 항목:

1. **선발 실험의 시간 누수 계약.** `docs/experiments/player-availability-2026.md` L 표의 “선발·출전 시간이 그 시각에 알려진 사실”은 수정 필요. 현재 경기 실제 출전 시간은 경기 전 입력으로 사용할 수 없다. 가중치는 이전에 완료·가용해진 경기만, 현재 경기는 당시 발표된 선발만 사용한다. 발표 시각을 입증하지 못하는 과거 자료는 시점 조건 대리 평가로 표시한다. 실제 누수 구현을 발견했다는 뜻은 아니며 코딩 전 명세 보완이다.
2. **정확도 향상과 비열등성을 분리.** 초안의 적중률 CI 하한 > −1%p는 정확도 향상 입증이 아니다. 사용자의 목표에 맞게 동일 경기의 적중률 차이·주 단위 paired CI·수정된 오답/새 오답을 주요 결과로 지정한다. 실제 향상 주장에는 CI가 0을 넘는지 확인하고, 불충분하면 판단 보류한다. LL/Brier/calibration도 함께 유지한다. 최소 표본과 실용적 개선 폭은 결과를 보기 전에 정하며 기존 실험 기준을 사후 변경하지 않는다.
3. **09:00 가용률을 직접 계산.** kickoff 이전 보유율만으로 아침 픽 가능 여부를 판단하지 않는다. 각 경기의 해당 09:00 KST decision_at에 양 팀 정보가 실제 저장되어 있었는지, 신선도·누락률을 리그/시즌별로 기록한다. AVAIL-TIME-1 수정 후 운영 DB에서 결과를 가리지 않은 readiness를 생성한다.
4. **공통 표본과 시장 비교.** 운영 모델은 전체 과거 경기로 학습하고 같은 manifest에서 후보를 비교한다. 제외 사유, 코드·원본 해시, 확정 후속 구간을 보관한다. 같은 decision_at의 시장 확률도 참고 기준으로 보고하되 시각 불명 배당은 운영 성능 근거로 사용하지 않는다.
5. **개인 픽 복기는 원인 단정 금지.** R2에서는 저장 당시 리스크와 사후 사실을 나누고, 졌다는 이유만으로 판단 오류라고 정하지 않는다. 좋은 판단/불운과 낮은 확률 선택/모델 오차를 구별한다. 사용자 선택 표본으로 전체 모델 정확도를 주장하지 않는다.
6. **리그 coverage 분모.** 역사적 최빈 경기 수는 리그 팀 수 변화 시 정상 시즌을 제외할 수 있다. 시즌별 공식 예정 경기 수를 별도 명세로 검토하되, 이번 통과 리그를 늘리기 위해 기준을 사후 바꾸지 않는다.

권장 진행 순서: 두 P2 수정 → 수정 SHA 회귀 QA → 실제 가용성/09:00 coverage 확인 → 시간 계약·정확도 목표·표본/분할 사전 등록 → 한 번의 후속 평가 → 독립 검증. 정확도 향상 가능성 검토이며 향상을 보장하지 않는다.
