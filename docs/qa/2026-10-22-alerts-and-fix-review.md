# 추가 QA: PR #42 / #43

2026-10-22 / Codex. 최종 **NEEDS_CHANGES**. 기존 세 지적의 수정은 확인했고, 추가 문제 2건을 재현했다.

## 대상

- 실행 main: `68da8ce4d4c54d435ac1b809856b2c725fd97feb`.
- #42 Base `715404d3e7e83094f6bb7c7892c230d07ce103e3`, Head `d48f3f44f892eb7bcae31c696602e047627ed5cb`.
- #43 Base `e4a6b75ff99400b72072d6559483a9ef0d46b0a8`, Head `d758fc1010d6aaeda54a645186013f0b7984b60e`.
- 두 PR은 조회 시 merge 완료. 독립 `getho-latest-qa` checkout/codex 브랜치를 최신 main으로 fast-forward하여 통합 상태를 검사했다.
- Windows, 기존 Python QA venv, 로컬 격리 PostgreSQL `127.0.0.1:15432/edge_test_morning`, Mock 데이터. 텔레그램은 가짜 Outbox/transport만 사용했다. 실제 메시지를 보내지 않았다.

## 기존 수정 재검증

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| PICK-STATE-1 종료 경기/미래 일정 | PASS | 기존 Codex 반례 통과, 기존 개인 픽 상태·관측·리비전 회귀 통과 |
| AVAIL-TIME-1 지연 저장 | PASS | captured −30h / stored −1h 반례가 1h 반환 |
| HIT-GATE-1 표현 | PASS | 비열등성과 개선 분리, −1%p 값 유지 확인 |
| 실험 시간 계약 | 문서 수정 확인 | 현재 경기 출전 시간 금지, 선발 시점 대리 평가, KST 주/동률/seed 등 명시. 학습 실행 검증은 아님 |

## 실제 실행

```text
python -m pytest -q --tb=short tests/integration/test_codex_oct22.py tests/integration/test_alerts.py tests/integration/test_personal_picks.py tests/integration/test_availability_readiness.py
python -m pytest -q --tb=short tests/integration/test_codex_oct22_extra.py
python -m ruff check apps/api/edge_api/services/alerts.py apps/api/edge_api/services/personal_picks.py workers/ingestion/edge_ingestion/alerts.py workers/ingestion/edge_ingestion/availability_readiness.py
npm run typecheck
```

- 변경 범위 **35 PASS** (99秒). 독립 추가 반례 **2 FAIL** (6秒).
- Python 경로: apps/api, ml, workers/ingestion. REQUIRE_DB_TESTS=1, TEST_DATABASE_URL=위 격리 DB.
- Alembic fixture의 base↔0013 적용 성공, append-only 관련 기존 테스트 포함. 별도 autogenerate check 미실행.
- 변경 Python Ruff 및 웹 typecheck PASS.
- `create_app().openapi()`와 `packages/contracts/openapi.json`을 JSON 객체 비교: **일치**.
- 최초 명령은 재현 파일명을 잘못 지정해 no tests ran. 올바른 `test_codex_oct22.py`로 수정해 위 결과를 얻었다. QA 스크립트 import/줄 길이 정리도 수행했다.
- 미실행: 전체 Python/web suite·build, 실제 브라우저, 실제 Telegram/API-Football, Linux cron/호스트 fallback, 동시 알림 프로세스, 운영 DB readiness, 원본 모델 학습.

## [P2] ALERT-DAY-1: 날짜 전환이 픽 누락의 해결로 오인됨

- 위치: `apps/api/edge_api/services/alerts.py:88`, `:123–128`, `_action`.
- 재현: DailyPick 0행인 상태로 10/23 08:50 KST 점검 → 이전 픽 날 누락 firing. 아무 행도 추가하지 않고 09:10 KST 재점검.
- 실제: **“해결: 2026-10-23 오늘의 픽 결정이 기록됐어요.”** 발신. 확인 시 DailyPick은 여전히 0행.
- 원인: key는 `pick_missing` 하나인데 대상 날짜가 바뀌고 새 날짜의 90분 유예가 시작되어 firing=False가 된다. 상태 전환을 실제 기록 생성으로 해석한다.
- 기대: 유예 진입/날짜 만료와 실제 결정 저장을 구분한다. 전날 미결 사건을 새 날짜 정상으로 덮지 않고, 실제 해당 날짜 행이 있을 때만 “기록됨”이라고 알린다.
- 수정 권고: 날짜별 incident identity 또는 이전 detail.pick_date를 추적하며 종료 사유를 분리한다. 만료 정책은 명시적으로 정한다.
- 재검증: 08:50→09:10→10:30, 전날/당일 결정 생성, 무추천 결정, 해결 전달 실패 후 날짜 전환. 가짜 sender로 검증 가능하다.

## [P3] PICK-SCORE-2: 원정 점수만 있는 관측은 사전 기록 차단에서 빠짐

- 위치: `apps/api/edge_api/services/personal_picks.py:293`.
- 재현: 예정 경기의 과거 FixtureObservation에 status=scheduled, home_score=NULL, away_score=1을 저장한 뒤 개인 픽 생성.
- 실제: HTTP 200, source_type=prospective_record. `_check_not_started`는 home_score만 검사한다.
- 기대: 어느 쪽이든 점수 관측이 있으면 동일한 모순 처리. away_score 검사를 추가하고 홈/원정 각각만 존재하는 경우를 검사한다.
- 제한: 모순 데이터를 주입한 방어 경계 테스트다. 정상 API-Football 파서는 finished 외 점수를 None으로 만들므로 정상 공급 경로에서 이 상태가 생긴다는 증거는 없다. 운영 발생을 주장하지 않고 낮은 심각도로 기록한다. 원래 finished 상태 반례는 해결됐다.

재현 도구: `scripts/qa/test_oct22_extra.py`를 해당 main checkout의 `tests/integration/test_codex_oct22_extra.py`로 복사해 실행한다. 기존 test helper/conftest에 의존한다. 기능 코드 수정 없음.

## QA 후 모델 개선 방향

새 정확도 수치는 없다. 이번 변경은 운영 안정성과 입력 시간 무결성 보강이다. 모델 채택은 **INCONCLUSIVE**.

1. 실제 운영 DB에서 수정 readiness를 생성하고 리그별 09:00 양 팀 보유율을 확인한다. 현재 `since`는 provider 제한 없는 최초 captured_at이므로 혼합 공급자/과거 backfill이 분모에 미치는 영향을 다음 데이터 QA에서 확인해야 한다. 이 위험은 이번에 별도 반례를 실행하지 않아 확정 결함으로 집계하지 않았다.
2. 최초 보고 나이와 가장 최근 가용 보고의 신선도를 구분한다. 현재 median_age_hours는 최초 보고 기반으로 정의되어 있어 최신 데이터 freshness로 사용하면 안 된다. 모델 입력 게이트에는 실제 선택 snapshot의 captured_at/created_at/age가 필요하다.
3. 실험 문서의 KST 주 및 HOME→DRAW→AWAY 동률 규칙을 구현과 맞춘다. 이전 Codex 탐색의 UTC 주/HOME→AWAY→DRAW 수치를 공식 실험 통과 판정에 그대로 가져오지 않는다.
4. 최소 20주는 검정력 보장이 아니다. 선수 후보 효과를 보지 않은 상태에서 실제 표본량·최소 경기 수·시즌 분할을 확정하고 후속 비교를 진행한다. 비열등성 통과와 정확도 개선은 계속 따로 보고한다.

다음 우선순위: ALERT-DAY-1 수정, 점수 방어 보완 → 새 SHA 재검증 → 운영 가용성 근거 확보 → 사전 등록 완성. 모델·main merge·배포·외부 메시지 발송은 수행하지 않았다.
