# 2026-10-19 독립 QA — 확률 보정 및 경기 복기

담당: Codex. **종합 NEEDS_CHANGES. 운영 모델 교체 승인하지 않음.**
Claude 기능 코드는 수정하지 않았으며 main 병합·배포·모델 버전 변경을 하지 않았다.

## 대상

| 대상 | Base SHA | Head SHA |
| --- | --- | --- |
| main | — | `d6cef46c5df38c8b0a444d4aca8e90697be4c1fb` |
| PR #10 확률 보정 | main과 동일 | `233074cd4d031e71e0c80b5e119b21d45173bf77` |
| PR #11 경기 복기 | main과 동일 | `7c972840d03480fe2ca76b68128a5b8c53b09fe7` |

2026-10-19 KST 원격 main과 두 PR ref를 직접 fetch했다. main은 10월 16일 마지막 검토와 같다.
열린 PR #3 자동 QA 워크플로는 이번 기능/모델 검토 범위에 포함하지 않았다.
분리된 기존 QA worktree를 재사용: `getho-latest-qa`의 `codex/qa-2026-10-19`는 PR #11,
`getho-pr5-qa`의 `codex/qa-calibration-2026-10-19`는 PR #10이다.
폴더의 과거 이름과 실제 검토 SHA를 혼동하지 않는다. 산출물은 `codex/main-ui-independent-qa`에 저장했다.

## 실행 결과

Windows, Python 3.12.13, 기존 frozen 의존성 venv, Node 24, WSL Docker PostgreSQL.
MockProvider와 QA 전용 127.0.0.1:15432의 `edge_test` / `edge_test_pr5_guard`를 사용했다.
운영 DB·API 키는 사용하지 않았다. DB 테스트는 REQUIRE_DB_TESTS=1이며 마이그레이션 base→head를 실행했다.

| 대상 | 실제 실행 명령 | 결과 |
| --- | --- | --- |
| PR #11 | `python -m pytest -q` | PASS 302, 282.00초 |
| PR #11 | `npm run test --workspace @edge/web` | PASS 96, 18파일 |
| PR #11 | `npm run typecheck --workspace @edge/web` | PASS |
| PR #11 | `npm run lint --workspace @edge/web` | PASS |
| PR #11 | `python -m ruff check .` | PASS |
| PR #11 | `npm run build --workspace @edge/web` | PASS 재시도 |
| PR #10 | `python -m pytest -q ml/tests/test_top_calibration.py workers/ingestion/tests/test_calibration_backtest.py --basetemp=.cache/pytest-calibration-1019` | PASS 8, 3.73초 |
| PR #10 | `python -m ruff check .` | PASS |
| PR #10 | `python -m edge_ingestion.cli backtest-calibration --out .cache/qa-2026-10-19-calibration.json` | PASS 수치 재현 |
| PR #11 코드 | 기존 F1~F4 독립 반례 9개 | FAIL 6 / PASS 3 |
| PR #11 코드 | `test_codex_review_availability.py` | FAIL 1, 4.57초 |
| PR #11 실제 page 함수 렌더 | `vitest run app/review/codex-scope.test.ts` | FAIL 1 |
| PR #10 코드 | `scripts/qa/test_calibration_boundaries.py` | FAIL 2 |

추가 Python 테스트는 QA 산출물 브랜치 루트에서 대상 PR worktree의 `apps/api`, `ml`,
`workers/ingestion`을 `PYTHONPATH`에 지정해 실행한다. DB 테스트 전 `TEST_DATABASE_URL`과
`DATABASE_URL`을 반드시 폐기 가능한 QA DB로 지정한다(테이블 초기화 포함).

```text
python -m pytest -q tests/integration/test_codex_review_availability.py
python -m pytest -q scripts/qa/test_calibration_boundaries.py
python scripts/qa/audit_calibration_timing.py ../getho-pr5-qa
```

PR #10의 전체 304개 테스트는 미실행이며 8개 관련 테스트만 실행했다.
최초 calibration 테스트는 sandbox 임시 디렉터리 권한으로 1 ERROR였고 작업 폴더 내 basetemp로 해결했다.
최초 Next build는 .next mkdir EPERM으로 실패했고 동일 명령을 권한 허용 환경에서 재실행해 통과했다.
복기 반례 최초 버전은 append-only 예측 행을 수정하려다 DB에서 차단됐다. 테스트 준비를 고쳐
예측 수정 없이 합성 fixture 시각만 이동하고 새 예측을 INSERT한 최종 버전에서 실제 조회 결함을 재현했다.
이 준비 오류를 제품 결함으로 세지 않는다. append-only 방어는 정상 작동했다.

## PR #11 발견 사항

### F5 / P1 — 경기 후 생성된 예측이 경기 전 기록으로 선택됨

- 위치: `apps/api/edge_api/services/queries.py:120`.
- `input_data_as_of <= kickoff_at`만 필터링하고 `created_at` 최신순으로 고른다.
  입력 시각은 예측이 사용자에게 실제로 제공 가능했던 시각과 다르다.
- 재현: 정상 기존 예측과, 입력 시각은 kickoff 1분 전이지만 생성 시각은 kickoff 3시간 후인
  새 예측을 저장한다. 경기를 finished로 설정하고 `review_day`를 조회한다.
- 실제: 기존 id=1 대신 사후 생성 id=65가 선택되어 적중률 요약에 들어간다.
- 기대: 사후 재생성 예측을 '경기 전에 분석이 말한 확률'로 표시하면 안 된다.
- 수정: 입력·생성/공개 가용 시각을 모두 cutoff로 검사하고, 사후 재분석이 필요하면 별도 표시/집계한다.
  실제 경기 전에 기록된 예측이 없으면 분석 없음으로 남긴다. 기존 기록이 없거나 여럿인 경우도 회귀 테스트한다.
- 증거: `tests/integration/test_codex_review_availability.py`.
  합성 방어 반례이며 실제 운영 DB에서 사후 예측이 유입됐다는 주장은 아니다.

### F6 / P2 — 검증 리그 요약에 전체 리그 분산을 사용함

- 위치: `apps/web/app/review/page.tsx:62`, `:119`; `apps/web/lib/review.ts`의 `luckNote`.
- `data.summary`는 검증 리그만 집계하지만 `scored`는 모든 리그다.
- 재현: 실데이터 모드, 검증 리그 10경기 p=0.5/0적중, 검증 전 리그 100경기 추가.
- 실제 page 함수를 await 후 renderToStaticMarkup한 결과: 0/10, 기대 5.0개 옆에
  '확률로 보면 흔히 나오는 범위예요'라고 표시한다.
- 기대: 해당 코드의 규칙으로도 검증 리그만 쓰면 SD=sqrt(2.5), 허용 폭 2.37이어서
  5개 차이는 '기대보다 꽤 적게'다. 무관한 리그 추가로 설명이 바뀌면 안 된다.
- 수정: summary와 variance에 같은 표본을 사용한다. demo에서는 전체 리그 사용을 유지한다.
- 증거: `scripts/qa/review-scope.test.ts`. 대상 PR worktree의
  `apps/web/app/review/codex-scope.test.ts`로 복사해 위 명령으로 실행한다.
  렌더 함수 검증이며 브라우저 E2E/RSC 통합 검증은 아니다.

## PR #10 모델 검증

### 수치 재현 — PASS, 운영 채택 증거 — 불충분

입력 SHA256 `cb944ef9f0bf6ec38cfa5f27ee91e81b57853a5105444c8d38a0bd9456e321f9`, 22,671행.
기존 예측 artifact로 보정 학습과 평가 CLI를 다시 실행했다. 원본 축구 데이터 수집 및 baseline 재학습은 하지 않았다.
원 보고서와 경로/생성 시각을 제외한 수치 차이 최대 4.34e-19로 재현됐다.

| 항목 | baseline | logistic candidate |
| --- | --- | --- |
| 선택 구간 2020-23, n=9,887 Log Loss | 1.00274742 | 1.00226401 |
| 후속 구간 2023-26, n=9,663 Log Loss | 0.99757645 | 0.99694397 |
| 후속 Brier | 0.59559089 | 0.59527211 |
| 후속 적중률 | 51.1849% | 51.1849% |
| 후속 60% 이상 평균 확률-적중률 절대 차이 | 0.03741288 | 0.00693291 |

후속 paired candidate−baseline Log Loss=-0.00063248,
주 단위 bootstrap 95% CI **[-0.00138971, +0.00010512]**. 개선 방향이나 0을 포함한다.
이 CI는 실험 구현을 재실행한 재현 결과이며 별도 bootstrap 구현으로 독립 교차 계산한 것은 아니다.
[전체 재현 JSON](2026-10-19-calibration-reproduction.json).

별도 시각 감사로 이전 시즌의 마지막 kickoff+3시간과 대상 시즌 kickoff를 비교했다.
현재 artifact에서 학습 결과 가용 시각 대리값보다 빠른 대상 경기는 모든 시즌 0개다.
실제 결과 관측 시각을 확인한 것은 아니다. [시각 감사 JSON](2026-10-19-calibration-timing.json).

### M1 / P1 (모델 채택 증거) — 이미 본 후속 구간과 완화된 gate를 승인 근거로 쓰면 안 됨

- 위치: `workers/ingestion/edge_ingestion/calibration_backtest.py:6`, `:26`.
- 사전 프로토콜 커밋 `cd8846f`에도 이미 2023-26에서 강팀 과소추정 3.5~4.4%p를 관측했다고 썼다.
  이후 같은 2023-26을 후속 평가에 사용하므로, 실행 전 코드 고정과 독립적인 미관측 시험은 다르다.
  프로토콜 문서는 이 커밋 이후 바뀌지 않았음을 확인했다. 결과를 본 뒤 코드 기준을 바꿨다는 주장은 아니다.
- 이번 G1/G2는 개선 >0 / >=0이면 통과하고 CI 상한을 조건으로 삼지 않는다.
  기존 QA 승격 기준인 선택 개선 0.001, 후속 개선 0.002, CI 상한<0을 만족하지 않는다.
- 수정 요청: 현재 결과는 탐색적 보정 실험으로 명시하고 '운영 승인 대기'를 일반 승격 기준 통과로 해석하지 않도록 한다.
  지금 규칙을 동결한 뒤 새 미관측 구간에서 평가하고 리그별·시즌별 결과, 전체 manifest/제외 사유,
  decision_at/가용 시각 및 보정 파라미터 이력을 제공한다.
- 연구용 코드를 보관하는 것과 운영 모델 승격을 구분한다. 운영 미배포 표시는 적절하다.

### M2 / P2 — logistic 보정의 단조 증가 계약이 보장되지 않음

- 위치: `ml/edge_ml/calibration.py:140`의 무제약 Nelder-Mead.
- 재현: top=[0.4,0.5,0.6,0.7,0.8], hit=[1,1,0,0,0]을 20번 반복해 fit.
- 실제: slope=-14151.67, map(0.4)=0.9999, map(0.8)=0.0001. overflow 경고도 발생한다.
- 기대: 문서의 단조 증가 계약을 보장하거나 학습 실패를 명시적으로 거절해야 한다.
- 수정: slope 비음수 제약, 수치적으로 안정된 sigmoid/loss, optimizer 성공/유한성 검사 및 경계 테스트.
  현재 실데이터에서 음수 slope가 발생했다는 주장은 아니다.

### M3 / P2 — isotonic에서 동일 확률 관측을 합치지 않아 잘못된 보정

- 위치: `ml/edge_ml/calibration.py:88`의 `_pav`.
- 재현: top=[0.6,0.6], hit=[0,1].
- 실제: 중복 knot에 대한 interp가 마지막 값을 골라 map(0.6)=0.9999.
- 기대: 동일 x의 관측은 하나로 합쳐 평균 0.5를 반환해야 한다.
- 수정: 같은 x를 합산해 가중 PAV를 수행하고 중복·순서 불변성을 테스트한다.
  이번 선택은 logistic이므로 이 결함만으로 보고된 logistic 수치가 틀렸다고 주장하지 않는다.
- M2/M3 증거: `scripts/qa/test_calibration_boundaries.py`의 2 FAIL.

## 지난 QA 추적

main SHA는 그대로이며 PR #11에서 F1~F4 관련 파일의 main 대비 diff도 없다.
오늘 PR #11 패키지로 동일 독립 테스트를 실행해 재현했다. 과거 PASS를 새 PR 전체에 전용하지 않는다.

| 기존 항목 | 오늘 상태 |
| --- | --- |
| F1 P1 선택 배당 2.06 → 계산 9.0 무통보 변경 | FAIL |
| F2 P1 미래 입력/생성/수집 시각 품질 게이트 통과 | FAIL |
| F3 P1 일정 변경 live/finished 픽 미무효 | FAIL 2; scheduled는 PASS |
| F4 P2 최근 미해결 경기의 재조회 한도 점유 | FAIL limit=1/100 |
| 뉴스 부분 저장 rollback/예외 전파 | PASS 2 |

## 한계와 Claude 다음 작업

실제 API-Football 호출, 실제 운영 성과, 새 PR Docker 이미지 smoke, 모바일 브라우저,
UI 기존 8건 전체 재검증, PR #11 계약 생성물 drift 독립 검사는 오늘 미실행이다.
localhost:3000 기존 실행 스택을 새 PR 실행 증거로 쓰지 않았다.

우선 F5 및 기존 P1을 수정하고 F6/M2/M3 회귀 테스트를 추가한다. M1은 새 미관측 평가가 필요하다.
수정된 Head SHA로 Codex가 다시 검증한다. CI 통과만으로 모델 정확도 개선을 승인하지 않는다.
