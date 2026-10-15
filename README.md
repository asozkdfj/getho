# EPL Edge Lab (working title)

EPL 경기의 통계 데이터와 시장 배당으로 **1X2 모델 확률 · 시장 공정확률(de-vig) · Edge · EV**를
계산하고, 2~3경기 조합을 분석하는 **스포츠 데이터/확률 분석 플랫폼** MVP입니다.

- 확률은 **통계 모델(Poisson + Elo)** 이 계산합니다. LLM은 확률을 정하지 않습니다(설명/구조화는 Phase 3).
- 베팅 실행·계정 연동·자동 주문 기능은 **없고, 만들지 않습니다**.
- 유료 API 키 없이 **결정적(deterministic) MockProvider + seed 데이터**로 전체가 동작합니다.
  데모 데이터의 결과·배당은 합성 데이터이며 실제와 무관합니다.
- 실데이터는 **API-Football** provider로 연결합니다(`DATA_PROVIDER=api_football`).
  [연동 가이드](docs/providers/api-football.md)를 참고하세요.

> 기획 문서: [`docs/epl_edge_lab_project_foundation.pdf`](docs/epl_edge_lab_project_foundation.pdf) ·
> 계획/리스크: [`docs/PLAN.md`](docs/PLAN.md) · 아키텍처: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
> 의사결정: [`docs/DECISIONS.md`](docs/DECISIONS.md) · 남은 일(왜 남았는지): [`docs/TODO.md`](docs/TODO.md)

## 빠른 시작 (Docker)

요구사항: Docker + Docker Compose v2. `.env` 파일 없이 동작합니다.

```bash
docker compose up -d --build     # 또는: make up
```

| 서비스 | URL |
| --- | --- |
| Web (Next.js) | http://localhost:3000 |
| API (FastAPI, OpenAPI 문서) | http://localhost:8000/docs |
| Postgres / Redis | localhost:5432 / localhost:6379 |

API 컨테이너는 시작할 때 `alembic upgrade head`를 실행하고, 로컬 compose에서는 seed도 자동으로
실행합니다. 둘 다 idempotent합니다. 샘플 데이터를 다시 만들거나 갱신하려면 아래 명령을 씁니다.

```bash
make seed        # = docker compose exec api python -m edge_ingestion.cli seed
make smoke       # 실행 중인 스택 end-to-end 점검
make down        # 정지 (DB 볼륨 유지) / 완전 초기화: docker compose down -v
```

`seed`는 몇 번을 실행해도 중복 행을 만들지 않습니다. 시간이 흘러 새 배당 스냅샷이나 결과가 생기면
그 부분만 **추가(append)** 됩니다.

## 로컬 개발 (Docker 없이)

요구사항: Python 3.12(`.python-version`으로 고정 — OpenAPI 생성 결과가 Python 버전마다 달라 contract 검사가 깨지는 것을 막기 위함), [uv](https://docs.astral.sh/uv/), Node 20.9+ (22 권장), PostgreSQL 16, (선택) Redis.

```bash
make install                         # uv sync + npm ci
cp .env.example .env                 # DATABASE_URL 등 확인
make migrate                         # alembic upgrade head
make seed-local                      # mock 데이터 + 예측 생성
make api-dev                         # http://localhost:8000
make web-dev                         # http://localhost:3000 (API_INTERNAL_URL=http://localhost:8000)
```

## 데이터 provider 전환

| `DATA_PROVIDER` | 필요한 것 | 설명 |
| --- | --- | --- |
| `mock` (기본) | 없음 | 합성 데이터, 오프라인, 결정적 |
| `api_football` | `API_FOOTBALL_KEY` | EPL 일정·결과·1X2 배당. [가이드](docs/providers/api-football.md) |

```bash
# .env 에 DATA_PROVIDER=api_football, API_FOOTBALL_KEY=... 설정 후
make check-provider     # DB에 쓰지 않고 키와 응답 형식 검증 (약 6~8 요청)
docker compose up -d --build
```

## 품질 명령

| 명령 | 내용 |
| --- | --- |
| `make lint` | ruff check/format, ESLint, Prettier |
| `make typecheck` | TypeScript `tsc --noEmit` |
| `make test-py` | pytest: 모델 계산, API, ingestion, DB 통합 테스트 |
| `make test-web` | Vitest |
| `make contracts` | FastAPI OpenAPI → `packages/contracts` TS 타입 재생성 |
| `make check` | lint + typecheck + test |

DB 통합 테스트는 `TEST_DATABASE_URL`(기본값 `postgresql+psycopg://edge:edge@localhost:5432/edge_test`)을
사용하며 **테이블을 TRUNCATE**합니다. Postgres에 접속할 수 없으면 로컬에서는 skip되고, CI에서는
`REQUIRE_DB_TESTS=1`이라 실패 처리됩니다. Docker로 테스트 DB만 띄우는 방법은 다음과 같습니다.

```bash
docker compose up -d postgres
docker compose exec postgres createdb -U edge edge_test
make test
```

CI(GitHub Actions)는 Python lint/test(+Postgres), 마이그레이션-모델 일치(`alembic check`), Web
lint/typecheck/test/build, API contract drift, `docker compose up` smoke 및 seed idempotency를
검사합니다.

## API

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/health` | DB/Redis 상태, git sha |
| GET | `/fixtures?date=YYYY-MM-DD&days=1..14&tz=Asia/Seoul` | 기간 내 경기 + 최신 배당/공정확률/모델확률 요약 |
| GET | `/fixtures/{id}` | 경기 상세 + 배당 스냅샷 이력 |
| GET | `/fixtures/{id}/prediction` | 최신 예측 snapshot: 모델확률, 공정확률, overround, Edge, EV, as-of 시각, 모델 버전 |
| POST | `/combinations/analyze` | 서로 다른 경기 2~3개 selection 조합 (`method: independence_approximation`) |

```bash
curl -s localhost:8000/fixtures?days=7 | jq '.fixtures[0]'
curl -s -X POST localhost:8000/combinations/analyze -H 'Content-Type: application/json' \
  -d '{"selections":[{"fixture_id":1,"outcome":"HOME"},{"fixture_id":2,"outcome":"DRAW"}]}'
```

## 저장소 구조

```
apps/api/            FastAPI 서비스, SQLAlchemy 모델, Alembic 마이그레이션, prediction job
apps/web/            Next.js(App Router) UI
workers/ingestion/   FootballDataProvider 인터페이스, MockProvider, idempotent 수집 job, Celery, CLI
ml/                  edge_ml: Poisson/Elo/강도 추정, de-vig, Edge/EV, calibration, 조합 (DB 의존성 없음)
packages/contracts/  OpenAPI 스키마 + 생성된 TS 타입 + 공유 enum
infra/docker/        Dockerfile, entrypoint
docs/                기획 문서, 계획, 아키텍처, 의사결정, TODO
tests/               교차 패키지 통합 테스트(tests/integration), 스택 smoke(tests/smoke)
```

## 원칙 요약

- 모든 timestamp는 `timestamptz`, UTC로 저장하고 UI에서 사용자 시간대로 변환합니다.
- `odds_snapshots`와 `predictions`는 append-only입니다. DB trigger가 UPDATE/DELETE를 거부합니다.
- prediction 행은 `fixture_id, model_version_id, created_at, input_data_as_of, probability_home/draw/away,
  market_odds_snapshot_id`를 필수로 가집니다.
- 모델 버전은 `name + semver + git sha + feature_set`으로 식별합니다.
- secret은 `SecretStr`로 다루고, 로그 포맷터가 접속 URL의 비밀번호와 key를 마스킹합니다.
- UI와 API는 확률을 "보장"으로 표현하지 않습니다. 모든 화면에 면책 문구가 들어갑니다.
