# 독립 QA: 최신 main과 UI 보강 PR #4

후속 main `d6cef46` 및 PR #5 재검증은 [후속 보고서](2026-10-16-independent-pr5-and-latest-main.md)를 참조한다.
이 문서의 main 표기는 아래 명시한 과거 SHA 기준이다.

검토: Codex, 2026-10-16 KST. **종합 판정: NEEDS_CHANGES.**
기존 수정 8건 중 7건은 실행 검증으로 확인했다. QA-02의 원래 정적 배당 불일치는 수정됐으나,
페이지 로딩 이후 예측이 갱신되는 경쟁 상황에서는 여전히 다른 배당으로 계산된다.
별도로 의사결정 시각보다 미래인 입력을 품질 게이트가 통과시키는 반례를 재현했다.
두 문제 모두 PR #4가 새로 만든 회귀는 아니다. 기존 main에 남은 문제이며, PR의 “8건 모두 해결”
주장과 검증 범위를 보완해야 한다. 기능 구현·모델 승격·main 병합·운영 배포는 하지 않았다.

## 대상과 과거 증거의 구분

| 대상 | SHA / 범위 |
| --- | --- |
| main / PR #4 base | `2d4b1abb9b8a7cbddc39fa932cee1628492d6723` |
| PR #4 head | `b916f2e851c32ac4b759a2acebadfd2423ec8923` (`claude/ui-qa-regression-tests`) |
| 검토 PR | https://github.com/asozkdfj/getho/pull/4 · 14파일, 요청 취소·시간대 로직 분리 및 웹 회귀 테스트 |
| QA 기준 브랜치 | `codex/model-qa-contract`의 `d104545` |
| 이번 작업 | `codex/main-ui-independent-qa`, 별도 `getho-independent-qa` worktree |
| PR 실행 폴더 | `codex/pr4-independent-review`, 별도 `getho-pr4-qa` worktree |
| 다른 열린 PR | #3 `26acb437afc2e68bd8177556194c271de2222aaa`, #5 `8ec96146563fba4c72003f22a52be3bc18883630`: 존재·범위 확인만, 이번 승인 대상 아님 |

기존 UI 문서는 `d8a72cae2cdfcb1db655dbf25213d9d89aed097d`를 검토했으며 문서 커밋은
`57d52ec59218cdc2e5a22a369688bbbf2cadeac2`이다. v0.2.0 정적 감사도 같은 개발 SHA가 대상이고
문서 커밋은 `01821b9737c9d97685f02258db804e54c6c8c863`이다. 후속 모델 재현 보고서는
`01821b9` 기준이며, 과거 Docker 미실행·당일 자정 픽 조건은 당시 기록이다.
최신 main의 미해결 상태로 그대로 전용하지 않았다.

README, ARCHITECTURE, TODO, MODEL_EVALUATION은 main에서 읽었다. 요청한 과거 QA 문서 3개,
PREDICTION_CONTRACT_V1, CODEX_QA는 main에 없어서 `codex/model-qa-contract`에서 읽었다.

## 실제 실행 환경·검사

Windows, Python 3.12.13, NumPy 2.5.4, uv.lock 고정 패키지, Node 24 호스트 테스트.
WSL Ubuntu 24.04 Docker: Postgres 16, Redis 7, Node 22 웹 빌드, Python 3.12 API.
QA compose project는 `getho-independent-qa`: 웹 3001, API 18001, DB 15432, Redis 16379.
PR #4 웹은 3002. 기존 실데이터 스택 3000/18000/5432는 유지했다.
DB 통합 테스트는 **QA 컨테이너의 edge_test만** 사용했다.

| 명령 / 검사 | 결과 |
| --- | --- |
| main `ruff check .`, `ruff format --check .` | PASS, 원본 Python 125파일 |
| main `PYTHONUTF8=1 REQUIRE_DB_TESTS=1 python -m pytest -q` | PASS **255**, skip 없음, 239초. 추가 Codex 반례 테스트를 넣기 전 원본 전체 실행 |
| main `npm test` | PASS **66** |
| main `npm run lint`, `npm run typecheck`, `npm run format:check` | PASS (LF checkout) |
| main Docker `compose ... up -d --build api web` | PASS; Next production build 포함 |
| `API_URL=http://127.0.0.1:18001 WEB_URL=http://127.0.0.1:3001 bash tests/smoke/smoke.sh` | PASS: 50 합성 경기, 4리그, 조합·웹 경로 |
| `alembic check` | PASS, 새 upgrade 없음. pytest가 downgrade base → upgrade head도 실행 |
| `python -m edge_api.export_openapi .cache/openapi.json`, openapi-typescript | PASS: OpenAPI LF 정규화 후 동일, 생성 TS 바이트 동일 |
| PR #4 `npm test`, `npm run typecheck`, `npm run lint` | PASS **84**, 15파일; 타입·lint PASS |
| PR #4 `docker build -f infra/docker/web.Dockerfile ...` | PASS, Node 22 Next build |
| `node scripts/qa/browser-regression.cjs` main 및 PR #4 웹 | PASS: 실제 Edge headless, 지연 응답 초기화, LA 시간대, 390px 모바일 |
| `python scripts/qa/validate_model.py` | PASS: 최신 main 모듈로 EPL 3,040경기 입력, 시험 1,140경기 재현 |
| 계약 unittest / 합성 JSONL 검사 | PASS 4 tests, 1 paired row; 실험 데이터 검증으로 오인 금지 |
| `python scripts/qa/concurrent_pick_probe.py` | PASS: 동시 4프로세스 모두 ID 1, 해당 날짜 DB 1행 |
| 추가 독립 Python 반례 2개 | **FAIL 2**: 아래 F1/F2. main 및 PR #4 Python 모듈 경로를 확인하고 각각 실행 |

초기 Windows 실행은 CP949 JSON 읽기 실패, 샌드박스 DB 접속 실패, CRLF Docker entrypoint exit 127이
발생했다. UTF-8, 권한이 허용된 QA DB 접속, 원본 Git blob과 동일한 LF checkout으로 재실행했다.
localhost 연결 지연은 127.0.0.1과 connect_timeout으로 해결했다. 초기 smoke 실행의 웹 포트가 기존
3000을 가리켰던 결과는 폐기하고 3001로 다시 통과했다. 이러한 초기 실패를 제품 회귀로 계산하지 않았다.
Mac 직접 실행은 미실행이며, Docker 공통 환경 검증이 Mac 장비 자체의 동등성을 증명하지 않는다.

## UI 8건 재검증

| ID | 판정 | 독립 확인 / 한계 |
| --- | --- | --- |
| QA-01 | PASS | main·PR 웹에서 요청을 지연시키고 초기화한 뒤 오래된 오류·로딩이 나타나지 않음. PR 단위 테스트는 성공 응답 경쟁도 검사 |
| QA-02 | **FAIL** | `prediction_odds` 사용으로 원래 기준 불일치는 수정. 그러나 선택 후 새 예측 생성 시 2.06 → 9.00 무통보 재계산; F1 |
| QA-03 | PASS | 실제 async 홈·리그 페이지 함수를 호출하여 highlights만 reject, 나머지 목록 HTML 유지. 홈에 실패 안내. 리그 페이지는 패널 숨김 |
| QA-04 | PASS | America/Los_Angeles 브라우저에서 카드 49개의 시간값이 KST 그룹 기준과 일치; main·PR 모두 |
| QA-05 | PASS | MockProvider 합성 상세 응답에 stale odds 경고를 주입, 실제 상세 페이지 함수의 경고 HTML 확인. helper·PR 소스 연결 검사도 통과 |
| QA-06 | PASS | 빈 Highlights 렌더링은 예정 분석 없음/표시 기준 미달을 설명하며 “비슷하다는 뜻” 단정 없음 |
| QA-07 | PASS | 기존 teamNews 테스트를 실제 실행: regulars_known=false 및 doubtful regular를 비주전으로 표시하지 않음 |
| QA-08 | PASS | 390px Edge 계산 스타일: 확률 25.6px, 결과 18.4px, main·PR 모두 |

추가 렌더링 테스트는 `apps/web/app/codex-independent.test.ts` 3건이다. API 호출을 mock하고 async
페이지 함수의 반환 트리를 renderToStaticMarkup으로 검사했다. 완전한 Next RSC/E2E라고 부르지 않는다.
합성 샘플은 `apps/web/lib/codex-qa-fixture.json`, 실제 공급자 자료가 아니다.

## 재현 가능한 발견 사항

### F1 · P1 · 선택 이후 갱신된 예측으로 배당이 무통보 변경됨

- 위치: `apps/api/edge_api/services/combinations.py:46`, `apps/web/lib/combination.ts:69`의 toRequest,
  `apps/web/components/CombinationBuilder.tsx` 선택 가격 표시. PR에서도 snapshot 식별자를 전송하지 않음.
- 재현: `tests/integration/test_codex_independent.py`. GET fixtures → 선택 홈 배당 2.06 저장 →
  새 배당 9.00 append → prediction job 갱신 → 시간을 갱신 뒤 POST combinations.
- 실제: HTTP 200, 결과 leg 9.00. 화면 선택 값은 서버에서 내려받은 기존 props의 2.06.
- 기대: 선택한 prediction/snapshot을 고정하거나, 변경 감지 후 재확인·refresh 요구. 예를 들어 409.
- 권장: 요청에 expected prediction ID 또는 odds snapshot ID를 포함하고 서버에서 일치 검증.
  최신 가격으로 계산하는 정책을 원한다면 사용자 확인을 거쳐 선택 UI도 함께 갱신.
- 기존 `test_combination_analyze`는 GET과 POST 사이 변경이 없어서 이 문제를 잡지 못한다.

### F2 · P1 · 결정 시각 이후 입력을 품질 게이트가 허용함

- 위치: `apps/api/edge_api/services/quality.py:71,79,89-95`,
  `apps/api/edge_api/services/queries.py:69`, `apps/api/edge_api/services/picks.py:169`.
- 재현: `apps/api/tests/test_codex_temporal_gate.py`. decision=2026-10-16 00:00 UTC,
  prediction.created_at/input_data_as_of, odds.captured_at, run.finished_at을 모두 +1시간으로 설정.
  나머지는 정상 확률·충분한 팀 이력·미시작 경기.
- 실제: 7개 품질 검사 모두 PASS. 음수 age는 최대 나이 조건을 만족하고 예측 생성 시각 검사는 없다.
- 기대: 미래 입력 제외. 조회에 as_of 상한을 적용하고 `0 <= age <= max_age`, prediction·학습 입력
  가용 시각 검사를 추가해야 한다. 불가능한 시각은 명시적으로 실패 처리.
- 범위: 합성 시각 반례 및 조회 코드 확인이다. **실운영에서 미래 결과가 실제 유입됐다는 증거는 아니다.**
  역사 시각 재실행/시계 불일치에 대한 방어와 시점 계약을 충족하지 못한다.

추가 감사 한계: `prediction_job.py:52,136`은 finished 상태와 kickoff로 결과를 선택하고 입력 시각을
kickoff로 기록한다. 결과 최초 수집·정정 이력이 없어 과거 decision_at의 학습 자료를 완전히 복원할 수 없다.
3시간 지연 연구가 이 실제 가용 시각을 대신 증명하지 않는다.

## 모델 재현 / 채택 판단

운영은 Poisson + Elo v0.2.0, 리그별 fit, newcomer prior, identity calibration이다. LLM이 아니다.
2018-19~2025-26 EPL 3,040경기를 캐시에서 읽었고 해시·시즌 구조 검사를 통과했다.
원본 공급자의 최신 자료를 다시 내려받거나 다른 공급자와 사실 대조한 것은 아니다.

| 조건 / 모델 | Log Loss | Brier | 정확도 | ECE |
| --- | ---: | ---: | ---: | ---: |
| 기존 convention v0.2.0 | **0.9831743008593544** | 0.585683 | 52.19% | 0.02743 |
| 결과 3h 지연 v0.2.0 | 0.983187 | 0.585692 | 52.19% | 0.02744 |
| 검증 선택 Poisson/Elo 확률 앙상블 | 0.982948 | 0.585560 | 52.28% | 0.02813 |

같은 시험 1,140경기(2023-24~2025-26), 검증 2020-21~2022-23. 후보 50:50 가중치는 검증에서 선택.
후보−운영 Log Loss 차이 −0.000239, ISO 109주 paired bootstrap 4,000회
95% CI **[−0.002998, +0.002407]**. 검증 개선 0.000811 < 0.001, 연구 게이트 FAIL.
후보 채택 **불승인**, 운영 모델 유지. 이미 사용된 시험 구간을 새 독립 holdout이라고 부르지 않는다.

산출물: `model-validation-results.json`, `model-validation-predictions.jsonl`(1,140행),
`scripts/qa/validate_model.py`. 기존 QA 도구를 최신 main 모듈로 재실행했다.
확률 유한성·합계·신규 팀 prior·시간순 학습·리그/컵 분리·중복/취소·append-only는 원본 테스트에서 검사.
실제 결과 가용 시각 보장은 INCONCLUSIVE/F2. 10개 리그 전체 재학습과 Claude 피로·순위·무승부 실험은
이번에 재실행하지 않았다. main 보고서는 모두 미채택이며, 해당 결과를 이번 독립 승인으로 전용하지 않는다.

## 오늘의 픽 / 실데이터 범위

- 09:00 KST~다음 09:00 경계, 시작한 경기 제외, 오래된 정보 차단, 재실행 불변성,
  무추천일 보존, 취소/연기 무효 이벤트, append-only는 원본 통합 테스트 PASS.
- 다중 프로세스는 별도 4프로세스 동시 시작 시험 PASS. 이는 대규모 부하 테스트가 아니다.
- 선정은 09시 이후 첫 요청/파이프라인 실행 시점이며 항상 정확히 09시에 실행된다는 보장은 없다.
  F2 때문에 과거 09시 시점 입력만의 완전 재현은 승인하지 않는다.
- `74.6%`는 main에 저장된 10리그 **시점 조건 대리 평가**다. 배당·수집 품질 게이트 미재현,
  동일 시험 구간으로 리그를 선별한 편향이 있다. 실시간 적중률로 인정하지 않는다.
- 이번 EPL QA 도구의 기존 daily_picks 비교는 09시~당일 자정 연구 조건을 유지한다.
  최신 09→09 서비스 또는 74.6%의 재현이라고 해석하지 않는다.
- 이번 최신 SHA 스택은 **mock**이다. 기존 실제 API-Football 스택의 과거 성공 결과를 최신 main/PR의
  실연동 PASS로 사용하지 않았다. 실제 API 재수집·경기 일정 이동의 실응답·장기 운영 성능은 INCONCLUSIVE.
- PR #5의 일정 변경·팀 뉴스 격리는 별도 SHA 검증이 필요하다. 이번 보고서로 승인하지 않는다.

## QA 브랜치와 main 차이 / 전달할 것

main에는 result_delay, fitted_at, decision_hour, coverage, 고유 key/길이/시간대 검사가 이미 반영됐다.
main은 추가로 day_start_hour=9 및 다음 날 09시 창, 주 단위 비교와 특성 실험 엔진을 갖는다.
**구 QA 브랜치 전체를 병합하면 최신 기능을 되돌릴 수 있으므로 필요한 QA 파일만 선별한다.**

main에 없는 항목:

1. `docs/qa/PREDICTION_CONTRACT_V1.md`, 합성 예시, `scripts/qa/check_prediction_contract.py`,
   `test_prediction_contract.py`: 이번 독립 QA 브랜치에 원본을 복사하고 실행했다.
2. `scripts/qa/validate_model.py`, 과거 `audit_model_v020.py`, 원본 해시와 경기별 QA 결과:
   이번에는 validate_model과 새 실행 결과만 가져왔다. JSONL 계약과 이 과거 도구 출력은 서로 다른 형식이다.
3. 과거 QA 문서 3개, `CLAUDE_MODEL_IMPROVEMENT_HANDOFF.md`, `docs/WORK_HANDOFF.md`, 양측 worklog:
   기존 QA 브랜치에 존재. 역사 문서는 당시 SHA와 함께 보존하고 최신 판정과 구분할 것.

후보 제출 시 전체 경기 manifest/제외 사유, 동일 decision_at, 관측 가용 시각 또는 대리 가정,
리그·시즌별 지표, paired 주 단위 CI, 후보 선택/후속 구간, 원본 해시와 실험 파라미터를 제출해야 한다.
현재 계약 검사는 구조 검사이며 실제 가용 시각의 진실성까지 증명하지 않는다.

## Claude 수정 요청 / 재검증 기준

1. P1 F1: snapshot을 고정하거나 재확인 정책 구현. 갱신 없는 기존 테스트와 새 갱신 경쟁 테스트 모두 통과.
2. P1 F2: as_of 필터 및 미래/음수 age 거부, 누락 timestamp fail-closed 정책. 미래 예측·배당·수집 각각,
   정확한 경계, 오래된 자료, 재실행을 회귀 검사할 것.
3. PR #4의 완료 설명을 위 범위에 맞게 수정. regex 소스 검사 외에 실행 가능한 렌더링 검사를 보완.
4. P2 결과 최초 가용 시각·정정 이력 설계와 학습 cutoff provenance를 보강. 관측자료가 없으면 proxy로 표시.
5. 후속 PR은 새 Head SHA로 테스트·diff를 다시 확인한다. 이번 PASS를 새 SHA에 자동 적용하지 않는다.

실행하지 않은 것: PR #3/#5 전체 리뷰, Mac 직접 실행, 실 API 최신 SHA 수집,
10리그·모든 후보 재학습, 장기간 운영 성과, 실공급자 일정 변경 E2E. 모델 교체는 승인하지 않는다.
