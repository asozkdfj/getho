# TODO: 남은 일과 "왜" 남았는지

품질 기준에 따라 의도적으로 미룬 항목은 모두 이유와 함께 여기에 적습니다. 코드에는 `TODO` 주석을
남기지 않았습니다.

| # | 항목 | 왜 아직 안 했나 | 언제/조건 |
| --- | --- | --- | --- |
| 1 | 실제 데이터 provider 연결 | 라이선스(재배포·표시·상업 이용) 검토가 먼저입니다. 인터페이스(`FootballDataProvider`)와 mock 경로가 완성돼야 한다는 기획서 순서를 따랐습니다. | Phase 1 후반, 한 곳 선정 후. timeout/retry/rate limit/circuit breaker, raw payload 보관(S3) 포함 |
| 2 | Calibration 학습(temperature/isotonic) | 보정은 예측-결과 쌍이 충분해야 의미가 있습니다. 지금은 `IdentityCalibrator`만 둡니다. | 사전 예측 300~500경기 누적 후 |
| 3 | 평가 지표(Brier, Log loss, calibration, CLV) 대시보드 | 실데이터 예측 이력이 없으면 지표가 의미 없습니다. `model_versions.metrics` 컬럼은 이미 있습니다. | Phase 2 |
| 4 | walk-forward 백테스트 / 하이퍼파라미터 튜닝 | 위와 같은 이유입니다. 현재 파라미터(가중치 0.6, 280 Elo/골, K=20)는 문헌 기반 초기값입니다. | Phase 2 |
| 5 | Dixon-Coles rho 추정 | 코드는 있지만(`rho` 파라미터) 추정에는 실데이터가 필요합니다. 기본값은 0입니다. | Phase 2 |
| 6 | Shin / power de-vig | MVP는 설명하기 쉬운 proportional만 씁니다(ADR-008). | Phase 2 |
| 7 | players, team_match_stats, injury_events, lineup_snapshots, llm_events 테이블 | Phase 1 범위 밖입니다(xG, 라인업, 부상, LLM은 Phase 2~3). 같은 append-only 패턴으로 추가합니다. | Phase 2~3 |
| 8 | Playwright E2E를 CI에서 실행 | CI 시간과 비용 때문입니다. 지금은 Vitest 단위 테스트와 compose smoke(HTTP + 조합 API)로 대신합니다. 로컬에서는 Playwright로 모바일/데스크톱 렌더링을 수동 확인했습니다. | 화면이 늘어나면 |
| 9 | 운영 배포(이미지 레지스트리, 마이그레이션 릴리스 단계, Sentry, structured JSON logs) | MVP는 로컬 compose가 목표입니다. production에서는 `RUN_MIGRATIONS_ON_STARTUP=false`, `SEED_ON_STARTUP=false`로 둡니다. | 공개 베타 전 |
| 10 | Celery beat 분리 | 로컬은 `worker -B` 하나로 충분합니다. 다중 worker에서는 beat를 단일 프로세스로 분리해야 합니다. | 배포 시 |
| 11 | SEO 페이지(`/matches/{home}-vs-{away}-{date}`, sitemap, SportsEvent 구조화 데이터) | Phase 3 범위입니다. 지금 URL은 `/fixtures/{id}`입니다. | Phase 3 |
| 12 | 지연/실패 표시 고도화 | 지금은 as-of 시각, 배당 수집 시각, 에러 페이지까지만 표시합니다. 수집 job 상태 테이블과 "데이터 지연" 배지는 실제 provider를 붙일 때 필요합니다. | #1과 함께 |
| 13 | `npm audit`: `braces` (high, ESLint 플러그인 → fast-glob → micromatch 경유) | 개발 전용 lint 도구 체인이라 런타임이나 배포 이미지에는 포함되지 않습니다. 아직 패치 버전이 없습니다(`braces *`). | upstream 패치 시 `npm update` |
| 14 | DB 레이어를 `packages/db`로 분리 | 지금은 ingestion이 `edge_api.db`를 import합니다(ADR-001). | ingestion을 별도 서비스로 분리할 때 |
| 15 | 로그인/즐겨찾기/알림, 분석 이벤트(PostHog) | 기획서상 트래픽을 확인한 뒤 추가합니다. | Phase 3+ |
