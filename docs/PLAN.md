# 계획 · 리스크 · 체크포인트

코드 작성 전에 정리한 내용입니다(Phase 0 + Phase 1 범위).

## A. 요구사항 요약

1. EPL 1X2 분석 플랫폼으로, 모델 확률·시장 공정확률(de-vig)·Edge·EV를 보여 줍니다. 베팅 실행은 없습니다.
2. 확률은 통계 모델(Poisson + Elo)이 계산하고, LLM은 Phase 3에서 설명/구조화만 맡습니다.
3. 모노레포 구성: Next.js(web), FastAPI(api), ingestion worker, ml, contracts, infra, docs, tests.
4. Postgres + SQLAlchemy/Alembic, Redis + Celery(최소 수준), Docker Compose 한 번으로 실행합니다.
5. Provider는 `FootballDataProvider` 인터페이스 뒤에 두고, API 키 없이 MockProvider와 seed로 전부 동작합니다.
6. 시간은 모두 UTC로 저장합니다. odds/prediction은 append-only snapshot이고, job은 idempotent합니다.
7. prediction 필수 필드: fixture_id, model_version, created_at, input_data_as_of, 확률 3개, market_odds_snapshot_id.
8. 모델 버전에는 semver, git sha, feature set을 기록합니다.
9. Poisson 기대득점 → score matrix → 1X2, Elo 보정, calibration 인터페이스(초기 identity).
10. API: /health, /fixtures, /fixtures/{id}, /fixtures/{id}/prediction, POST /combinations/analyze.
11. 조합은 서로 다른 경기 2~3개이고 독립 근사이며, 응답에 근사임을 명시합니다.
12. Web 화면: 경기 목록, 상세, 조합, 방법론/면책. 모바일에서 읽을 수 있어야 하고 "보장" 같은 표현은 금지합니다.
13. 테스트: 확률 합 1, de-vig 합 1, 재실행 시 중복 없음. CI와 README도 갖춥니다.

## B. 리스크 / 모호한 점과 처리

| # | 리스크 | 처리 |
| --- | --- | --- |
| 1 | 고정 날짜 seed는 시간이 지나면 "오늘/이번 주" 화면이 빈다 | Mock 일정을 실행 시점 기준 4일 그리드에 앵커링 → 항상 오늘/이번 주 경기 존재 ([ADR-003](DECISIONS.md)) |
| 2 | prediction 재실행 시 중복/오염 | 유니크 키 `(fixture, model_version, odds_snapshot, input_data_as_of)` + `ON CONFLICT DO NOTHING`, as-of는 벽시계가 아닌 입력 데이터 시각 |
| 3 | odds 저장 단위(행/selection) | 한 행 = 한 북메이커의 1X2 세트 (de-vig 단위 일치) ([ADR-002](DECISIONS.md)) |
| 4 | 조합에 어떤 배당을 쓰나 | 각 경기 최신 prediction이 참조한 스냅샷 배당 (화면 수치와 일치), 응답에 snapshot id/시각 포함 |
| 5 | 실데이터 없이 팀 강도 추정 | Mock이 숨겨진 "진짜" 강도로 직전 시즌+현재 시즌 결과를 생성 → 모델이 이를 학습 |
| 6 | Celery 범위 | worker + beat 1개 task(수집→예측). seed는 CLI 동기 실행 |
| 7 | 계약(contract) drift | OpenAPI → openapi-typescript 생성 + CI diff 검사 + enum 일치 테스트 |
| 8 | 컨테이너 시작 시 마이그레이션 | 로컬 compose에서만 자동, production은 별도 릴리스 단계 (문서화) |
| 9 | Dixon-Coles 범위 | `rho` 파라미터로 구현, 기본 0 (Phase 2에서 추정) |
| 10 | E2E 브라우저 테스트 비용 | CI는 Vitest + compose smoke. Playwright E2E는 TODO |

## C. 데이터 흐름

```
MockProvider ──(DTO)──> ingestion jobs ──upsert/append──> PostgreSQL
                                                         │
             prediction job: 결과(kickoff < now)로 fit ──┤── predictions (append-only)
                                                         │
                         FastAPI (조회 시 de-vig/Edge/EV 재계산) ──> Next.js
```

## D. 체크포인트

| CP | 내용 | 상태 |
| --- | --- | --- |
| P0-1 | 모노레포 골격, uv workspace, npm workspaces, .env.example | ✅ |
| P0-2 | `edge_ml` 계산 모듈 + 단위 테스트 | ✅ |
| P0-3 | API 골격, ORM 모델, Alembic(append-only trigger), /health | ✅ |
| P0-4 | Dockerfile, docker-compose, Makefile, CI | ✅ |
| P1-1 | Provider 인터페이스, MockProvider, idempotent ingestion + 테스트 | ✅ |
| P1-2 | prediction job, model_versions, API 엔드포인트 + 통합 테스트 | ✅ |
| P1-3 | contracts 생성, Web 4개 화면, Vitest | ✅ |
| P1-4 | compose 통합 검증(smoke), 문서/TODO 정리 | ✅ |
