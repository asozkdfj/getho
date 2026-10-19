# 아침 PR 독립 QA — 2026-10-19, Codex

최종 판정: **NEEDS_CHANGES**. Claude 기능 소스는 변경하지 않았다.

| 대상 | Base SHA | Head SHA | 범위 판정 |
| --- | --- | --- | --- |
| #14 shadow 기록 | 2f72ef776aa61b5e4e8a6520fe5fce4dc2e7de88 | 2d766d8b530cb25e7b5874aa9902b8194c21f561 | NEEDS_CHANGES |
| #15 결과 관측 이력 | 8bc5fc9bc99a507ad447e9235ae34a17c1a5e0ad | 86e009d7b309779496e244c49a2d834b0b30fb49 | 아래 통합 테스트 범위 PASS, 실운영 INCONCLUSIVE |
| #16 선수 정보 시점 | 86e009d7b309779496e244c49a2d834b0b30fb49 | 3a42c18aa50ea8762cb2631d8e6f067a88dc23c9 | NEEDS_CHANGES |

확인 main: `8bc5fc9bc99a507ad447e9235ae34a17c1a5e0ad` (#14 병합됨).
실행은 별도 `codex/qa-morning-2026-10-19` worktree의 #16 head에서 수행했다.
PR별 전체 테스트를 각 head에서 독립 실행했다는 뜻이 아니다. #14 picks/shadow 소스는
#16까지 diff 없음 확인. localhost:3000의 기존 스택을 최신 PR 검증으로 사용하지 않았다.

## 실제 실행

Windows / Python 3.12.13 / Node 24 / 별도 WSL Docker PostgreSQL 15432.
`PYTHONPATH=apps/api;ml;workers/ingestion`, `REQUIRE_DB_TESTS=1`.
DB는 `edge_test`와 새 반례용 `edge_test_morning`으로 분리했다. 운영 DB는 변경하지 않았다.

| 명령/검사 | 결과 |
| --- | --- |
| `python -m pytest -q --basetemp=.cache/pytest-morning` | 389 PASS, 430.69초; 기존 테스트와 이전 독립 회귀 12개 포함 |
| `python -m pytest -q tests/integration/test_codex_morning.py` | 새 반례 3 FAIL, 7.92초; 앞의 389개와 별도 실행 |
| 웹 Vitest | 100 PASS; 실제 복기 페이지 함수 렌더 회귀 1개 포함 |
| Next.js lint/typecheck/build | PASS |
| `python -m ruff check .` | PASS |
| OpenAPI export / openapi-typescript 재생성 비교 | JSON 의미 및 TS 내용 일치 |
| Alembic upgrade 및 populated migration 회귀 | Python suite에서 PASS, 최신 0009 사용 |
| 별도 `alembic check` | 미실행 |
| 최신 Docker 이미지 build/smoke, 실제 API-Football 신규 호출 | 미실행 |
| 브라우저 수동 8건 전체 재검증 | 이번에는 미실행; 기존 테스트와 혼동하지 않음 |

## MORN-1 / P1 — 늦게 저장된 선수 행이 과거 주전 판단에 포함

- #16 `apps/api/edge_api/services/team_news.py:55`.
- `known_by`는 최근 경기 선택 subquery에 적용되지만 바깥 선수별 출전 시간 집계에 없다.
- 같은 과거 경기에 결정 시각 전 선수 A, 결정 시각 후 선수 B 기록을 넣고
  `regular_players(..., known_by=decision_at)` 호출.
- 실제: 미래 저장 선수 B가 주전 후보에 포함됨. 기대: 해당 행 제외.
- 영향: 부분 백필된 경기의 역사적 선수/결장 전력 분석에 시점 누수. 현재 운영 승패
  모델이 이 변수를 사용해 실제 오염됐다고 주장하지 않는다.
- 요청: 외부 집계에도 행별 `created_at <= known_by` 적용. 부분 수집/여러 선수/경계 시각 재검증.

## MORN-2 / P2 — 잘못된 결장 응답이 확인 완료·결장 없음으로 변환

- #16 `workers/ingestion/edge_ingestion/providers/api_football.py:412`.
- 해당 경기 injury 응답에서 player.id/name을 누락한 가짜 응답을 주입(네트워크 호출 없음).
- 실제: 파싱 실패를 건너뛰고 `AbsenceReport(absences=[], covered={'123'})` 반환.
- 이어지는 수집은 지원 리그에서 빈 결장 스냅샷을 만들 수 있다. 기대: 잘못된 해당 경기
  정보는 unknown/partial 또는 오류로 남겨야 한다.
- 요청: 관련 경기 파싱 실패를 coverage에 반영하고 마지막 정상 기록을 빈 정상 응답으로
  덮는 해석을 방지. 완전 빈 정상 응답과 malformed 응답을 따로 회귀 테스트.
- 실제 공급자에서 이 malformed 응답이 관측됐다는 뜻은 아니다.

## MORN-3 / P1 — 부가 shadow 조회 오류가 오늘의 픽 선정 중단

- #14 `apps/api/edge_api/services/picks.py:185` (통합 #16에서도 동일).
- 선정 대상 리그 밖의 shadow 전용 예측 조회(두 번째 조회)에 RuntimeError를 주입.
  핵심 픽 예측 첫 조회는 정상이며 두 ID 집합이 겹치지 않는 것을 테스트에서 확인.
- 실제: `publish_daily_pick`까지 예외 전파. 기대: 픽 생성과 shadow 오류 증거 기록.
- 원인: `all_preds` 조회가 try/savepoint 바깥에 있다.
- 요청: 부가 조회부터 저장까지 전체를 오류 격리 트랜잭션 안에 두고, 조회 실패 및
  중간 저장 실패에서도 핵심 픽을 보존하는 회귀 테스트 추가.

새 반례 파일: `scripts/qa/test_morning_boundaries.py`.
대상 head의 `tests/integration/test_codex_morning.py`로 복사해 대상 conftest와 실행한다.
이 QA 브랜치의 오래된 기능 코드에서 직접 실행하는 용도가 아니다.

## 이전 수정 재검증 및 별도 남은 위험

main `2f72ef776aa61b5e4e8a6520fe5fce4dc2e7de88`에서 F1~F6 및 M2/M3 회귀가 통과했다.
당시 Python 363 / 웹 100 / Ruff / lint / typecheck / build / 계약 비교 PASS.
이번 389개에도 이전 독립 회귀 12개를 포함해 PASS했다. 오래된 FAIL을 현재 미해결로 유지하지 않는다.

별도 **P2**: `0006_model_version_code_fingerprint.py` downgrade가 다른 fingerprint를 가진
동일 구형 identity 두 행에서 `uq_model_versions_identity` UniqueViolation으로 실패한다.
격리 DB `edge_test_pr5_guard`에서 실제 재현했으며 rollback 후 revision 0006 유지.
`scripts/qa/probe_populated_fingerprint_downgrade.py`는 이 DB 이름/15432만 허용한다.
기존 #13 변경의 populated downgrade 위험이며 #16 신규 회귀로 분류하지 않는다.
새 0009의 중복 content hash 이후 downgrade 제약은 PR에서 이미 공개된 별도 제한이다.

## 모델 판단 / Claude 인계

이번 변경은 기록·시점 계약 보강이다. 새 모델의 예측력 개선을 증명하는 시험이 아니다.
후보 모델 채택 INCONCLUSIVE, 운영 모델 교체 승인 없음.
이전 보정 재실행 LL 0.996944 대 baseline 0.997576, 차이 CI [-0.001390, +0.000105]로
확정 개선 아님. 탐색 결과 표기와 새로운 후속 평가 등록은 개선으로 인정한다.

Claude: MORN-1/3 우선, MORN-2 및 populated rollback 방안 수정 PR 제출.
Codex: 새 head에서 세 독립 반례, 전체 Python 및 계약/웹 회귀 재검증.
배포·main merge·모델 버전 변경은 수행하지 않는다.
