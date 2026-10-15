# 아키텍처

## 구성 요소

| 구성 요소 | 위치 | 책임 | 의존 |
| --- | --- | --- | --- |
| `edge_ml` | `ml/` | 순수 계산: Poisson score matrix, Elo, 공격/수비 강도, de-vig, Edge/EV, calibration, 조합 | numpy, scipy |
| `edge_api` | `apps/api/` | FastAPI, ORM 모델, 마이그레이션, prediction job, 조회/분석 서비스 | edge_ml |
| `edge_ingestion` | `workers/ingestion/` | Provider 인터페이스·구현, 수집 job, 파이프라인, Celery, CLI | edge_api, edge_ml |
| `@edge/contracts` | `packages/contracts/` | OpenAPI 스키마, 생성 TS 타입, 공유 enum | – |
| `@edge/web` | `apps/web/` | Next.js UI (서버 컴포넌트가 API 호출, 조합 POST는 same-origin proxy) | contracts |

의존 방향은 `ingestion → api → ml`이며 순환이 없습니다. provider 고유 코드는
`edge_ingestion/providers/` 밖으로 나가지 않습니다. core는 provider 독립 DTO(`TeamData`, `FixtureData`,
`OddsData`)만 알면 됩니다.

## 데이터 흐름

```
           ┌──────────────────────── edge_ingestion ────────────────────────┐
Provider ─>│ get_teams / get_fixtures / get_odds  ->  jobs.run_ingestion     │
(Mock)     │   teams/fixtures: UPSERT (값이 바뀐 경우에만)                    │
           │   odds_snapshots: INSERT ... ON CONFLICT DO NOTHING (append)     │
           └───────────────┬─────────────────────────────────────────────────┘
                           v
                      PostgreSQL  <──── predictions (append-only)
                           ^                     ^
                           │      edge_api.services.prediction_job
                           │        1. kickoff < now 인 종료 경기로 모델 fit
                           │        2. now 이전 최신 odds snapshot 선택
                           │        3. INSERT ... ON CONFLICT DO NOTHING
                           v
                FastAPI 조회: snapshot 행에서 fair prob / Edge / EV 재계산
                           v
                Next.js (SSR, cache: no-store)
```

`run_pipeline`(CLI `seed`, Celery task)은 수집 → 예측 → 픽 정산 → (선정 시각 이후) 오늘의 픽 선정을 한
트랜잭션에서 실행합니다. 이때 `pg_advisory_xact_lock`으로 동시 실행을 직렬화하고, 실행마다
`ingestion_runs`에 성공/실패를 기록합니다(실패는 별도 트랜잭션).

### 오늘의 픽

```
predictions(최신, 현재 모델) ─> quality.assess (7개 점검) ─> edge_ml.picks.select_pick
                                                            │  (백테스트와 같은 함수)
                                                            v
             daily_picks INSERT ... ON CONFLICT (provider, pick_date, revision) DO NOTHING
                                                            │
     fixture 종료/취소 ─> settle_daily_picks ─> daily_pick_events (settled | voided, 1회)
```

- 근거(evidence JSONB)에 후보 전체와 제외 사유, 선택된 예측의 확률·특성·데이터 점검 결과, 그 시점의
  백테스트 요약, 모델 버전, `is_demo`를 저장합니다. 화면 설명은 이 값만 인용합니다.
- `/picks/today`는 선정 시각 전에는 `scheduled`를 돌려주고, 이후 첫 요청이나 파이프라인이 선정합니다.
  어느 쪽이 먼저든 결과는 하나입니다.

### 평가

- `edge backtest`(ml/edge_ml/backtest.py)가 실데이터로 walk-forward 평가를 하고 JSON 보고서를 만듭니다.
  `seed`가 커밋된 보고서를 `model_evaluations`에 넣습니다(sha256 중복 방지).
- `/performance`는 그 보고서와, 저장된 예측을 실제 결과로 채점한 실시간 지표(모델 vs 시장)를 함께
  돌려줍니다.

## 스키마

| 테이블 | 주요 컬럼 | 키 / 제약 |
| --- | --- | --- |
| `teams` | provider, provider_id, name, short_name, league | UQ(provider, provider_id) |
| `fixtures` | provider_id, season, round, kickoff_at(UTC), home/away_team_id, status, score | UQ(provider, provider_id), CK(home≠away), IX(kickoff_at) |
| `odds_snapshots` | fixture_id, bookmaker, market, odds_home/draw/away, captured_at, raw_payload | UQ(fixture, bookmaker, market, captured_at), CK(odds>1), **append-only trigger** |
| `model_versions` | name, version(semver), git_sha, feature_set, calibration, params, metrics, artifact_uri | UQ(name, version, git_sha, feature_set) |
| `ingestion_runs` | provider, started_at, finished_at, status, counts, error | IX(provider, started_at), **append-only trigger** |
| `model_evaluations` | model_name/version, feature_set, dataset, report(JSONB), report_sha256 | UQ(report_sha256), **append-only trigger** |
| `daily_picks` | provider, pick_date, tz, revision, status, fixture_id, prediction_id, model_version_id, outcome, probability, input_data_as_of, evidence, policy, published_at | UQ(provider, pick_date, revision), CK(published면 필수 컬럼), **append-only trigger** |
| `daily_pick_events` | pick_id, event(settled/voided), actual_outcome, hit, reason | UQ(pick_id, event), **append-only trigger** |
| `predictions` | fixture_id, model_version_id, market_odds_snapshot_id, created_at, input_data_as_of, probability_home/draw/away, expected_goals_*, features | UQ(fixture, model_version, odds_snapshot, input_data_as_of), CK(합=1, 0..1), **append-only trigger** |

### Idempotency와 snapshot 규칙

- **input_data_as_of**는 사용한 입력 중 가장 늦은 시각입니다. 즉
  `max(odds snapshot captured_at, 학습에 쓴 마지막 경기 kickoff)`이고 벽시계 시각이 아닙니다.
  그래서 입력이 같으면 키도 같고, 재실행해도 아무것도 바뀌지 않습니다.
- 새 배당이나 새 결과가 생기면 키가 달라지므로 새 행이 추가되고, 과거 행은 그대로 남습니다. 백테스트와
  감사에 쓸 수 있습니다.
- 코드나 모델 파라미터가 바뀌면 git sha 또는 semver가 바뀌어 새 `model_versions` 행이 생기고, 예측도
  새로 쌓입니다.
- 경기 시작 이후(`kickoff_at <= now`)에는 예측을 만들지 않습니다. 학습 데이터와 배당도 `now` 이전 것만
  씁니다(look-ahead 방지).

## 모델 (v0.2.0, `poisson_strength_v1+elo_supremacy_v1+newcomer_prior_v1`)

1. 가중 MLE(Maher)로 공격/수비 강도를 추정합니다. 시간 감쇠는 0.005/day이고, 4경기분 prior로 리그 평균
   쪽으로 수축합니다.
2. Elo: K=20, 홈 어드밴티지 60, 골차 multiplier를 적용하며, 경기 순서대로 replay합니다.
3. Supremacy 결합: `S = 0.6·(λh−λa) + 0.4·(EloDiff/280)`, 총 득점 `T = λh+λa`는 유지합니다.
4. `λh=(T+S)/2, λa=(T−S)/2`로 0~10골 score matrix를 만들고 재정규화해 1X2를 얻습니다.
5. Calibrator는 `Calibrator` 프로토콜을 따르며, 현재 구현은 `IdentityCalibrator`입니다.
6. 승격팀 prior(v0.2.0): 모든 경기에 시즌 정보가 있으면, 직전 시즌에 없던 팀은 그 시즌 시작 시점 하위
   3팀(`newcomer_reference_teams`)의 평균 Elo에서 출발하고, 공격/수비는 하위 3팀의 평균 쪽으로
   수축합니다. 아직 한 경기도 안 치른 팀(시즌 개막 전 승격팀)도 같은 강등권 수준 prior를 받습니다.
   예측 `features`의 `prior_home`/`prior_away`(`data`, `promoted_relegation_level`,
   `unseen_relegation_level`, `league_average`)로 어떤 출발점을 썼는지 확인할 수 있습니다.

## 시간대

DB 세션은 `SET TIME ZONE 'UTC'`, 컬럼은 `timestamptz`입니다. naive datetime은 `ensure_utc`에서 거부합니다.
`GET /fixtures`의 `date`는 `tz` 기준 로컬 날짜로 해석합니다. Web은 서버 렌더링 때 `DEFAULT_TZ`로
그리고, hydration 이후에는 브라우저 시간대로 표시합니다.

## 보안 / 운영

- 설정은 pydantic-settings를 쓰고, `DATABASE_URL`, `REDIS_URL`, API key는 `SecretStr`입니다. repr이나
  dump에 노출되지 않습니다.
- `RedactingFormatter`가 로그에서 `user:pass@`와 `api_key=`를 마스킹합니다.
- 컨테이너는 non-root(uid 10001 / node)로 실행합니다. web은 API 호스트를 브라우저에 노출하지 않습니다
  (proxy route).
- 실제 provider를 연결할 때는 timeout, retry, rate limit, circuit breaker를 갖추고 라이선스를 확인해야
  합니다([TODO](TODO.md)).
