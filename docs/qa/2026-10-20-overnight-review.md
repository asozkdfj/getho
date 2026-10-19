# 밤사이 변경 독립 QA — Codex, 2026-10-20 KST

판정: **NEEDS_CHANGES**. 모델 승격 승인 없음.
실행 대상 main `4f45edbe5647c731601b917945963cf696db7d7a`,
독립 worktree/브랜치 `getho-latest-qa` / `codex/qa-overnight-2026-10-20`.
이전 검토 main `22f9b074ad11c41dbefe494a97c3630c97cbbf7b` 이후 PR #21~#30을 확인했다.
실행은 통합 main 기준이며 각 개별 head에서 전체 suite를 별도 실행한 것이 아니다.

## 주요 대상 SHA

| PR | Base | Head |
| --- | --- | --- |
| #21 CLV 실험 | 22f9b074ad11c41dbefe494a97c3630c97cbbf7b | 6530b338e24e7e706417b0cb6610ee55eb8b9dd7 |
| #22 서버 준비 | 1fdb042c7661484ce8d2cd42941a79a385797bf6 | 10526da9adae62a54286b5df0e9f69d59aa7e015 |
| #23 보정 채점 | 1fdb042c7661484ce8d2cd42941a79a385797bf6 | 9990f7c8a412eed2719125e90b6eb09624871acf |
| #24 live CLV | e0407998b2a248debcbacf8640e72e1a4159c5e5 | 83809ed16dfe3b5500ba80bc4cd8ac6e480fb0d4 |
| #25 연구 페이지 | e0407998b2a248debcbacf8640e72e1a4159c5e5 | ccb8fc4834484b4ce434dbcc4bf4bcb5dbe2c4d9 |
| #26 슈팅 실험 | 60607c317d7c1c9d47d9b7896719db03a594cae9 | 728a1082a1533ec81cafbe807a195a66786fa8cd |
| #27 공급자 비교 | 60607c317d7c1c9d47d9b7896719db03a594cae9 | 196ab556f862bd18504f3eff9f61f4adabe3fa7e |
| #28 shadow-v2 | 60607c317d7c1c9d47d9b7896719db03a594cae9 | 7f44451aef9f83b8b0a4ca470173742f0b0b5993 |
| #29 시간대 조합 | 60607c317d7c1c9d47d9b7896719db03a594cae9 | f97eedde6e1b8774ce000c32f11576b9ea0fde9c |
| #30 backup cron | 04d41a73501200e11e1c325c98c23b7e6cb0e411 | f13c1f6a5411221b38107c1088c8adcf5142f453 |

## 실행 범위

Windows / Python 3.12.13 / Node 24 / 별도 QA PostgreSQL 15432, edge_test_morning.
운영 스택 변경·서버 설치·모델 교체·main merge 없음.

- `python -m pytest -q`: 최종 결과는 아래 후속 실행 결과 절에 기록.
- 새 `apps/api/tests/test_codex_shadow_result_timing.py`: **1 FAIL** (5.01초), 아래 SHOT-1 재현.
- 웹 `npm run test -- --run`: **109 PASS**.
- 웹 `npm run typecheck`, `npm run lint`, `npm run build`: PASS.
- `python -m ruff check .`: PASS.
- OpenAPI export와 저장된 JSON의 의미 비교: PASS. Windows 기본 인코딩으로 첫 비교가 실패해
  PYTHONUTF8=1로 다시 export했다. 계약 불일치가 아니며 generated TS 재생성 비교도 PASS.
- 서버 backup/setup 원본 Git blob을 LF 그대로 추출해 `bash -n`: PASS.
  Windows checkout CRLF 검사 실패와 구분했다. cron 실제 설치·백업·복원은 미실행.
- 실제 API 호출·신규 xG 커버리지 감사·브라우저 수동 UI 점검·Docker smoke: 미실행.

## SHOT-1 / P1 — 과거 시점 슈팅 특성에 늦게 정정된 경기 결과 반영

위치: `apps/api/edge_api/services/shadow_v2.py:43`의 shot_histories 및 71행의 f.home_score 사용.
통계는 latest_statistics(as_of=at)로 제한하지만 종료 여부·스코어·킥오프는 현재 Fixture에서
읽는다. 결과 관측 이력의 가용 시각을 적용하지 않는다.

독립 재현은 DB 조회 반환값을 mock하고 실제 shot_histories/ShotHistory를 실행했다.
6개 과거 경기와 결정 전 통계를 제공한 뒤 고정 at으로 특성을 계산한다. 한 경기 결과를
at 이후 정정된 값으로 바꾸고 같은 at으로 다시 조회하면 finishing 특성이
`[0.833333, -0.833333]`에서 `[0.555556, -0.555556]`로 바뀐다.
기대는 동일 결정 시각에서 동일한 당시 관측 결과다.

이는 이미 저장된 append-only shadow 행이 덮어써졌다는 뜻이 아니다. 과거 as-of 재현과
결정 시각을 고정한 재실행에서 현재 결과를 사용하는 문제다. 실제 운영 예측 오염 규모는
이번 합성 테스트로 측정하지 않았다.

요청: FixtureObservation에서 at까지 저장된 최신 상태·스코어·일정을 조회하고 해당 버전만
통계와 결합한다. 관측 이력이 없는 결과는 명시적으로 제외하거나 가정 연구로 분리한다.
late finish, late score correction, 일정 정정의 DB 회귀 테스트도 추가한다.
같은 패턴의 live_clv._BaseRates도 현재 스코어+킥오프 3시간을 쓰므로 함께 검토할 필요가 있다
(CLV 경로는 이번에 별도 독립 반례를 실행하지 않았음).

재현 파일: `scripts/qa/test_shadow_result_timing.py`를 대상 main의
`apps/api/tests/test_codex_shadow_result_timing.py`로 복사해 실행.

## 모델 성능 주장 검토

`ml/reports/backtest-shots.json`에서 기존 gate 함수를 다시 호출해 저장된 gate와 일치함을
assert했다. **집계 산술/판정 재계산**이며 원본 CSV부터 학습과 경기별 bootstrap을
독립 재실행한 것은 아니다. 이번 환경에서 해당 원본 캐시/경기별 산출물을 확보하지 않았다.

| 보고서 후속 9,663경기 | Log Loss | Brier | 적중률 |
| --- | ---: | ---: | ---: |
| 운영 | 0.997576 | 0.595591 | 51.18% |
| sot_and_finishing | 0.992379 | 0.592319 | 51.57% |
| 시장 | 0.976913 | 0.582078 | 52.74% |

후보-운영 LL 차이 -0.005197, 보고서 주 단위 CI [-0.006809, -0.003594], 121주.
검증 개선 0.005092. 보고된 기준 통과는 산술상 일치한다.
그러나 이미 다른 실험에 사용한 2023~26 구간이며 통계 관측 시각도 킥오프+3시간 가정이다.
이 결과만으로 실제 오전 9시 개선이나 운영 승격을 승인하지 않는다.
후보는 시장보다 LL이 약 0.015467 나쁘다. 시장 비교를 생략해 우위를 주장하면 안 된다.

shadow-v2는 고정 후보, 2026-11-02~2027-03-28, 최소 1,500경기를 별도 등록했다.
정확히 09:00가 아닌 실제 decided_at 정책이며, 일 단위 주 분석/주 단위 보조 분석이다.
입력 공급자도 학습과 달라 #27의 실제 응답 비교와 시점 보존 검증이 필요하다.
자료가 충분하지 않으면 불확실로 남기며 기간/기준을 사후 완화하지 않는다.

## 이전 결함 및 다음 담당

CQ-1(리그 이름 합산), STAT-1(한 팀 통계 수집 후 다른 팀 재시도 누락)은 해당 구현의
수정이 이번 범위에 없다. 전체 suite에 기존 독립 회귀도 포함해 재확인한다.
Claude: SHOT-1 및 이전 결함 수정, 원본 해시와 경기별 예측 manifest 제공.
Codex: 새 SHA 회귀, 실제 공급자/결과 관측 시점과 동일 경기 모델 비교 재검증.

## 후속 실행 결과

전체 Python 실행: **439 PASS / 5 FAIL, 589.73초**. 다음 세 실패는 cp949 기본 인코딩으로
UTF-8 문서를 읽다 발생했고 PYTHONUTF8=1로 해당 세 테스트만 재실행해 **3 PASS (3.28초)**:

- ml/tests/test_shadow_v2.py::test_protocol_constants_match_the_document
- apps/api/tests/test_contract_enums.py::test_outcomes_match
- workers/ingestion/tests/test_calibration_confirmatory.py::test_frozen_map_matches_the_report_and_the_protocol

나머지 두 실패는 기존 CQ-1/STAT-1 독립 반례다. STAT-1은 여전히 첫 520행 후 추가 0행이다.
새 SHOT-1은 전체 suite가 수집을 마친 뒤 별도 추가·실행했으므로 위 444개에 포함되지 않는다.
합산하면 서로 다른 테스트 442개가 통과했고 기능 반례 3개가 실패했지만,
**한 번의 전체 실행이 442 PASS / 3 FAIL이었다고 표현하지 않는다.**
인코딩은 테스트에서 명시적 encoding='utf-8' 사용 또는 실행환경 PYTHONUTF8=1 고정 권장.

후속 개발 우선순위: SHOT-1/P1과 STAT-1/P1 → CQ-1/P2 → 독립 원본 모델 재현 및
실제 shadow 기록의 시점 감사. 모델 성능 주장은 집계 검증 범위 INCONCLUSIVE로 유지한다.
