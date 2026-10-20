# 2026-10-21 독립 QA — 최신 main 및 PR #37

담당 Codex. 최종 판정 **NEEDS_CHANGES**. 모델 교체·main merge·배포 없음.

## 대상과 환경

실행 main: `3f7a546bd6519df66063d2f11163e3a40f2e8965`.
이전 QA main: `4f45edbe5647c731601b917945963cf696db7d7a`.
격리된 getho-latest-qa / codex/qa-overnight-2026-10-20에서 main을 fast-forward했다.
기존 QA 전용 테스트는 보존했다. 문서·재현 도구는 codex/main-ui-independent-qa에 게시한다.
PR #31~36은 통합 main에서 실행했고 개별 head 전체 테스트를 했다는 뜻이 아니다.
#37은 정확한 head의 코드·등록 이력·저장 report 산술을 검토했다.

| PR | Base SHA | Head SHA |
| --- | --- | --- |
| #37 | 797b3c4dcc8ee7f01789bb5fc81c62b9acfc13ba | e47a1ee529b71365f09c6c0d2527be171388a5b9 |
| #36 | 4de4b693e7efc3f7778bbfae5570b7729cb21849 | 41efd9dcd42b89130aa8a0f45f46617ebdb95e67 |
| #35 | 4de4b693e7efc3f7778bbfae5570b7729cb21849 | a8ac7c9fe468d88c5941b9afbdced0f4a079adb9 |
| #34 | d474d6935123c076b0bc3c903cdc61b7b6853bc6 | c12fcf626ac95177555beb2f5994ad1fcc9921cd |
| #33 | d97226043b1f6fd26834c575fb52d35fa5cb32e0 | eb89c1383b38940f8dccb65f93a30f0c431ce0de |
| #32 | 41c40281ff81f533cf0a80777b8639a46b4f5f89 | c8d2ff47ec38e97e14ac335916fdf8211b141da0 |
| #31 | 4f45edbe5647c731601b917945963cf696db7d7a | eae9e595c2de22ac784bb20f5918cee595837af9 |

Windows, Python 3.12.13, Node/Next.js 로컬 의존성, 별도 PostgreSQL 127.0.0.1:15432/edge_test_morning.
PYTHONUTF8=1, PYTHONPATH는 대상 checkout의 apps/api;ml;workers/ingestion을 명시.
운영 DB에 접근하지 않았다.

## 테스트 결과

- 변경 범위 Python DB/단위 회귀: **62 PASS / 1 FAIL, 191.76초**.
  대상: test_betman, test_shadow_v2, test_live_clv, test_collection_quality,
  test_match_statistics, test_xg_backtest, test_history_export,
  test_codex_partial_statistics, 새 test_codex_betman_asof.
- 별도 독립 CQ-1 테스트: **1 PASS**. 기존 mock에 새 출력 필드 provider_id가 없어
  첫 실행 AttributeError가 났으며 QA fixture만 보완했다. 제품 결함으로 집계하지 않는다.
- DB fixture의 Alembic downgrade base → upgrade head 완료(0011 포함).
- 웹 npm test: **111 PASS**. npm run typecheck / lint / build: PASS.
- Python `ruff check apps/api/edge_api workers/ingestion/edge_ingestion ml/edge_ml`: PASS.
  새 독립 Betman 회귀 테스트 Ruff PASS.
- 테마 실제 모듈의 Node VM 재현: 아래 2건 FAIL. 브라우저 실측과 구분.
- xG 저장 예측의 검증/후속 LL 및 paired CI 재계산: PASS(저장 정밀도 허용 1e-6).
- PR #37 저장 표본/CI에 따른 verified 판정 산술: 11개 일치, 8개 통과.
  선정 집합의 사전 조건은 FAIL.

첫 제한 환경 실행은 DB 접속 불가로 48 setup errors/14 pass 및 오래된 CQ mock 1 fail이었다.
격리 DB를 명시한 권한 조정 재실행으로 대체했다. 첫 웹 build는 컴파일 후 파일 복사 EPERM,
권한 조정 재실행 성공. 이 환경 오류를 제품 실패로 합산하지 않는다.
전체 Python suite, 실제 API-Football 호출, Docker 앱 smoke, OpenAPI 재생성 비교,
실제 브라우저 테마/모바일/기존 UI 8건 수동 확인은 **미실행**이다.
기존 UI의 자동 테스트 통과와 수동 재현 완료를 혼동하지 않는다.

## 기존 결함 재검증

- SHOT-1: PASS. 최신 DB 테스트에서 늦은 스코어 정정·결과 관측·킥오프 이력 검증.
  과거 MagicMock 기반 테스트의 빈 이력 통과만으로 판정하지 않았다.
- STAT-1: PASS. 기존 독립 partial_statistics 반례와 새 팀별 재시도 회귀 통과.
- CQ-1: PASS. 동명 England/Kenya 리그가 분리됨. 새 출력 필드에 맞춰 독립 mock 보완.

## BETMAN-TIME-1 / P1 — 미래 경기 연결 결정이 과거 조회를 바꿈

위치: apps/api/edge_api/services/betman.py:98, :384, :391.
status_report(at)은 배당은 created_at<=at으로 제한하지만 latest_mappings에는 as_of가 없다.
purchase_blockers도 mapping.created_at을 검사하지 않는다.

실제 PostgreSQL 재현:
1. now에 실제 관측 배당 3개와 수동 경기 연결을 저장.
2. at=now+1분으로 조회하면 purchasable=3, blocked=0.
3. DB 시계를 now+1시간으로 이동해 manual_reject를 추가.
4. 같은 at으로 재조회하면 purchasable=0, blocked=3. 과거 결과가 달라진다.

기대: 과거 at까지 존재한 최신 매핑을 사용해 동일 결과를 유지.
미래에 처음 연결한 이벤트 역시 과거 구매 가능으로 소급되면 안 된다.
권장: latest_mappings에 as_of를 전달하고 created_at과 id로 당시 최신 버전을 선택.
alias/수동 정정/미래 최초 연결에 대한 DB 회귀 추가.
재현 파일 scripts/qa/test_betman_asof.py를 대상 repo의 tests/integration/
test_codex_betman_asof.py로 복사해 pytest 실행. 기존 test_betman helper를 사용한다.
실제 구매 기능은 없지만 향후 과거 가상 정산의 후보 집합을 오염시키므로 P1.

## THEME-1 / P2 — 다른 탭의 테마가 DOM에 적용되지 않음

위치 apps/web/lib/theme.ts:31. storage 이벤트는 React 구독자에게 통지만 한다.
light 적용 → 저장값을 다른 탭에서 dark로 바꾼 상황 → storage listener 호출 결과:
readTheme=dark, documentElement.data-theme=light.
기대: 표시 상태와 실제 배경 모두 dark. 이벤트 경로에서 DOM 적용도 동기화하고 회귀 추가.

## THEME-2 / P2 — 저장소 차단 시 토글이 라이트에 머묾

위치 apps/web/lib/theme.ts:19, :40.
getItem/setItem 예외 상태에서 applyTheme(light) 후 readTheme=system,
nextTheme(readTheme())=light다. 클릭을 반복해도 dark로 넘어가지 못한다.
기대: 영구 저장 없이도 현재 페이지에서는 3개 상태 순환.
권장: 메모리 상태를 유지하며 저장소와 동기화하는 테스트 추가.

두 테마 건은 실제 TypeScript 모듈을 transpile하여 DOM/storage 모형에서 실행했다.
브라우저 hydration/시각 대비 검증은 미실행.
재현: apps/web에서 `node <QA repo>/scripts/qa/reproduce_theme.cjs`.

## LEAGUE-SELECT-1 / P2 — PR #37의 사전 선정 조건 위반

위치 workers/ingestion/edge_ingestion/league_verification.py:3-8, EXTRA_LEAGUES, run.
사전 등록은 각 시험 시즌이 통상 경기 수 90% 이상인 리그만 선정한다고 한다.
제출 report는 sc.1 2024-25 200경기, sc.2 159경기다.
같은 리그의 2023-24/2025-26은 각각 228/180경기로 통상 시즌과 일치한다.
200/228=87.72%, 159/180=88.33%이므로 90% 미달인데 대상에 포함됐다.
코드에도 리그·시즌 기대 경기 수와 이 선정 조건을 검사하는 과정이 없다.

권장: 시즌별 기대 경기 수 근거·커버리지·제외 사유를 명시하고 조건 미달을 검사.
다른 분모를 사용했다면 사전 규칙에 부합하는 근거를 제출.
결과에 맞춰 기준을 낮추지 말고 기존 11개 결과는 탐색 자료로 보존, 적격 집합을 분리.
통과 8개 산술은 맞지만 대상 선정 준수 판정은 FAIL.
리그 공급자 ID의 실제 DB 대조 및 운영 리그 확대는 승인하지 않음.

등록 4ca20fc 2026-10-20 16:04:35Z → report generated_at 16:05:21Z
→ 결과 커밋 e47a1ee 16:05:55Z 순서 확인.
이 기록만으로 실제 최초 실행 시각이나 '결과를 보지 않았음'을 인증할 수는 없다.

## 모델 검증 — xG PR #34/#35

등록 병합 4de4b69 2026-10-20 15:40:22Z → report 15:41:46Z
→ 결과 커밋 a8ac7c9 15:42:25Z 순서 확인.
등록 병합과 최신 main 사이 xg_backtest.py diff 없음.
저장 예측 중복·확률 범위/합 검사와 LL 재계산을 실제 수행했다.

| 구간 | n | 운영 LL | 슈팅 기준 LL | xG 교체 LL | 슈팅+xG LL |
| --- | ---: | ---: | ---: | ---: | ---: |
| 검증 2024-25 | 2,913 | 0.989725 | 0.984297 | 0.982312 | 0.981864 |
| 후속 2025-26 | 2,916 | 1.002903 | 0.999865 | 1.001350 | 1.000181 |

후보는 검증에서 선택한 sot_finishing_plus_xg.
후속 후보-슈팅 LL=+0.000316336, 주 단위 paired 95% CI
[-0.001367837, +0.001978885], 39주, 4,000회, seed 20261016.
저장 report와 각 차이는 1e-6 이내다.
예측 파일 SHA256 fcb5e69a51ccf5fce338c2de9089ba98ed4562a1154d596298467faba2ce5f26.
판정 **기준 미통과 / 개선 여부 INCONCLUSIVE** 유지. 모델 채택 승인 없음.

원본 API xG CSV 확보·팀 연결 재현·원본부터 학습은 미실행이다.
관측 시각 없이 kickoff+3시간을 가정한 과거 대리 평가이고 기존에 사용한 구간이므로
실제 미래 예측 성능을 입증한 것은 아니다. 사전 등록 준수의 코드/기록 범위만 확인했다.

## Claude 수정 순서와 재검증

1. P1 Betman as-of 매핑 고정. 새 독립 DB 회귀와 미래 최초 연결 반례 통과 필요.
2. P2 리그 선정 분모/90% 조건 검사 및 표본 manifest 정리. 기준 사후 완화 금지.
3. P2 테마 storage 이벤트·저장 불가 상태 수정. 실제 다중 탭/차단 저장소 브라우저 검사.
4. 새 Head SHA를 제출하면 해당 SHA 기준 재검증. 이 보고서의 PASS를 자동 승계하지 않음.

GitHub PR #32/#36/#37에 수정 요청, #31/#35에 재검증 범위를 댓글로 남긴다.
