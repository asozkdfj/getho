# 독립 후속 QA: PR #5 및 main d6cef46

담당: Codex, 2026-10-16 KST. **판정: NEEDS_CHANGES. 모델 교체 승인 보류.**
기존 테스트는 통과하지만 독립 경계 테스트에서 네 종류의 문제가 재현된다.
실제 운영 사고나 미래 정보 사용을 관측했다는 뜻은 아니다. 합성 데이터로 방어 조건의 결함을 입증했다.

## 대상과 환경

- PR #5 base: `2d4b1abb9b8a7cbddc39fa932cee1628492d6723`.
- PR #5 최초 실행 head: `8ec96146563fba4c72003f22a52be3bc18883630`.
- PR #5 최종 head: `1d5262e295b95325ca3875351aba3e5a1ca7d212`.
  최종 head에서 경계 테스트를 다시 실행했다. PR은 검토 중 이미 병합됐으며 Codex가 병합하지 않았다.
- 후속 main: `d6cef46c5df38c8b0a444d4aca8e90697be4c1fb`.
  PR #6~#9의 픽 신뢰성·시장 비교·골 시장·신뢰도/자동 조합 변경도 포함한다.
- Windows, Python 3.12.13, Node 24, WSL Docker PostgreSQL.
  개발 폴더와 분리한 `getho-pr5-qa`, `getho-latest-qa` 사용.
- DB는 QA 전용 127.0.0.1:15432의 `edge_test`, `edge_test_pr5_guard`.
  운영 DB·API 키·실데이터 스택을 변경하지 않았다. 수집 테스트는 MockProvider 사용.
- QA 도구/문서는 `codex/main-ui-independent-qa`에서만 작성했다.

## 실제 실행 결과

| 대상 | 명령 / 검사 | 결과 |
| --- | --- | --- |
| PR #5 최초 head | `python -m pytest -q` | PASS 270 / 182.98초 |
| PR #5 최초 head | `npm run test --workspace @edge/web` | PASS 66 |
| PR #5 최초 head | web lint/typecheck, Ruff check/format | PASS |
| PR #5 최종 head | 아래 독립 PR #5 테스트 | FAIL 4, PASS 3 / 11.78초 |
| main d6cef46 | `python -m pytest -q` | PASS 296 / 204.56초 |
| main d6cef46 | `npm run test --workspace @edge/web` | PASS 93 / 17파일 |
| main d6cef46 | `npm run lint --workspace @edge/web`, `npm run typecheck --workspace @edge/web`, `python -m ruff check .` | PASS |
| main d6cef46 | 기존 반례 2개 + PR #5 독립 테스트 7개 | FAIL 6, PASS 3 / 19.42초 |
| main d6cef46 | 저장된 시장 예측 22,671행 산술 재계산 | PASS, 아래 한계 참조 |

독립 테스트는 QA 브랜치 루트에서 대상 코드의 `apps/api`, `ml`, `workers/ingestion`을
`PYTHONPATH`에 지정한다. `TEST_DATABASE_URL`과 `DATABASE_URL`은 반드시 폐기 가능한 QA DB로,
`REQUIRE_DB_TESTS=1`, `PYTHONUTF8=1`을 설정한다. 테스트 fixture는 DB를 초기화한다.

```text
python -m pytest -q tests/integration/test_codex_pr5.py
python -m pytest -q tests/integration/test_codex_pr5.py tests/integration/test_codex_independent.py apps/api/tests/test_codex_temporal_gate.py
python scripts/qa/audit_exported_market.py ../getho-latest-qa --out docs/qa/2026-10-16-market-artifact-audit.json
```

PR #5 최종 head의 전체 270개 테스트는 미재실행이다. 최초 head 결과를 최종 head의 전체 검증으로 전용하지 않는다.
새 main의 Docker build/smoke, 브라우저 UI 8건 전체, 실제 API-Football 호출, 원본 데이터 재수집 및
전체 모델 재학습은 이번 후속 검토에서 미실행이다. 이전 main의 성공은
[이전 보고서](2026-10-16-independent-main-pr4.md)에 별도로 보존한다.

## 재현 가능한 발견 사항

### F3 — P1: 일정 변경 픽의 무효 처리가 최초 재수집 상태에 따라 달라짐

- 위치: `apps/api/edge_api/services/picks.py:364` (main d6cef46).
- 재현: 픽을 발행하고 해당 경기 kickoff를 3일 뒤로 변경한다. 최초 갱신 상태를
  scheduled/live/finished로 각각 설정한 뒤 `settle_daily_picks`를 호출한다.
- 실제: scheduled만 voided=1. live는 미무효, finished는 settled=1로 성과 집계에 들어간다.
  독립 테스트의 세 경우 중 두 경우 FAIL.
- 기대: 발행 구간 밖으로 옮겨진 경기를 무효로 보는 현재 정책은 수집 지연이나 최초 관측 상태에
  따라 달라지면 안 된다. 원래 선정 구간과 무관한 경기 결과가 적중률을 바꾸지 않아야 한다.
- 수정 요청: 아직 정산되지 않은 픽의 구간 이탈을 상태별 정산보다 먼저 판단하고 append-only 이벤트로 기록한다.
  scheduled/live/finished, 구간 내 시간 변경, 09:00 경계, 중복 정산을 회귀 테스트한다.

### F4 — P2: 최근 미해결 경기가 재조회 한도를 반복 점유함

- 위치: `workers/ingestion/edge_ingestion/jobs.py:315`의 kickoff 내림차순 및 limit.
- 재현: 조회 대상 미종료 경기 101개를 만들고 provider가 빈 목록을 반환하게 한다.
  기본 한도 100으로 두 번 호출한다. 한도 1/경기 2개에서도 동일하게 재현된다.
- 실제: 같은 최근 100개만 반복 조회한다. 가장 오래된 경기는 두 번 모두 요청되지 않는다.
  응답 누락이 지속되면 동일 쿼리가 반복되어 오래된 경기는 계속 누락될 수 있다.
- 기대: 일시적으로 해결되지 않는 최신 경기 때문에 다른 후보가 영구적으로 제외되지 않아야 한다.
- 수정 요청: 마지막 시도 시각/커서/공정한 재시도 큐 등으로 순환을 보장한다.
  전체 backlog와 선택된 batch의 미해결 수를 구분하고 101개 이상의 회귀 사례를 유지한다.

### F1 — P1: 선택 후 예측 갱신 시 배당 무통보 변경 — 최신 main에서도 FAIL

- 위치: `apps/api/edge_api/api/routes/combinations.py`의 최신 예측 조회,
  `apps/web/lib/combination.ts`의 fixture/outcome만 보내는 요청 계약.
- 상세 재현은 이전 보고서 및 `tests/integration/test_codex_independent.py`.
  화면 선택 배당 2.06 이후 새 배당 9.0과 예측을 저장하면 기존 선택 요청이 200/9.0으로 계산된다.
- 요청에 기대 prediction/snapshot 식별자를 포함해 불일치를 거절하거나 재확인을 요구한다.

### F2 — P1: 미래 시각 품질 게이트 — 일부 개선, 잔여 반례 FAIL

- 최신 `services/queries.py:78`은 `Prediction.input_data_as_of <= as_of`를 추가했다.
  따라서 과거 보고서의 조회 cutoff 부재를 그대로 현재 코드에 적용하지 않는다.
- 그러나 `services/quality.py`의 `assess`는 의사결정보다 1시간 뒤의 예측 생성·입력·배당 수집·수집 완료
  시각을 준 단위 반례에서 모든 품질 검사를 통과시킨다. 음수 age의 하한과 실제 가용 시각 방어가 부족하다.
- `apps/api/tests/test_codex_temporal_gate.py`로 재현. 조회 cutoff와 별개로 quality의 직접 호출도 방어하고,
  예측 생성/입력/배당/결과 관측의 가용 시각을 명시적으로 검사한다.
- 실제 운영 누수 발생을 확인한 것은 아니다. 과거 결과의 관측 시각 이력이 없어 kickoff 기반 대리 평가와
  실제 의사결정 시점 평가를 구분해야 한다.

## 통과한 추가 경계

팀 뉴스 저장 후 ProviderError 발생 시 savepoint 안의 부분 저장만 롤백되고 예측과 성공 수집 기록은
커밋된다. RuntimeError는 숨기지 않고 호출자로 전달되며 외부 롤백 후 경기 저장도 남지 않는다.
이 두 경우와 scheduled 상태의 구간 이탈 무효 처리가 PASS다.

## 시장 모델 및 신뢰도 수치 독립 확인

새 main의 `backtest-market.predictions.jsonl.gz`를 별도 stdlib 스크립트로 읽어 중복,
확률 유한성/범위/합, 동일 경기 집합의 Log Loss·Brier·적중률을 재계산했다.
원본 SHA256: `cb944ef9f0bf6ec38cfa5f27ee91e81b57853a5105444c8d38a0bd9456e321f9`.
원본 재학습이 아닌 **저장된 예측의 산술 감사**다.

후속 구간 2023-24~2025-26, n=9,663:

| 모델 | Log Loss | Brier | 적중률 |
| --- | --- | --- | --- |
| production | 0.99757645 | 0.59559089 | 51.185% |
| market_only | 0.97691283 | 0.58207777 | 52.737% |
| blend_w0.25 | 0.97995330 | 0.58391526 | 52.603% |

선택 구간 2020-21~2022-23은 n=9,887. 상세 값은
[감사 JSON](2026-10-16-market-artifact-audit.json)에 있다.
후속 구간 production 확률 65% 이상은 1,145경기/76.769%, 55~65%는 1,808경기/60.896%로
저장된 보고서의 약 77%/61% 주장과 일치한다. 이는 모든 경기 적중률이나 하루 한 픽의 운영 성과가 아니다.

보고서의 연구 gate는 통과/미배포로 기록돼 있다. 이번 감사에서는 bootstrap 신뢰구간과 calibration을
독립 재계산하지 않았다. 배당 관측 시각, 예측 실제 가용 시각, 완전한 제외 manifest가 없어
09:00 KST 운영 조건 재현을 확인하지 못했다. fitted_at이 kickoff과 같은 행은 567개이며,
kickoff보다 뒤인 행은 0개다. JSON에 별도 계수했다.
그 수치만으로 누수를 단정하지 않으며, decision_at과 실제 학습 완료 시각 계약을 추가 검증해야 한다.
**수치의 산술 일치는 PASS, 운영 모델 교체 적합성은 INCONCLUSIVE / 승인하지 않음.**

## Claude 수정 요청과 재검증

1. P1 F3 및 기존 F1/F2 수정. 새로운 Head SHA에서 독립 반례 및 관련 기존 테스트 재실행.
2. P2 F4 순환 재조회 보장, 기본 한도 초과 사례 회귀 테스트.
3. 후보 모델은 동일 decision_at/가용 시각/manifest/원본 해시와 주 단위 paired bootstrap,
   calibration·리그/시즌별 결과를 제공. 선택 이후 새 평가 구간을 유지한다.
4. 수정 전 테스트 실패를 없애기 위해 평가 기준이나 구간을 변경하지 않는다.

현재 최종 판단은 NEEDS_CHANGES다. 기능 코드 수정, main 병합, 운영 배포, 모델 버전 변경은 수행하지 않았다.
