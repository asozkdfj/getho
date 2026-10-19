# EPL Edge Lab (working title)

축구 리그 경기의 통계 데이터와 시장 배당으로 **1X2 모델 확률 · 시장 공정확률(de-vig) · Edge · EV**를
계산하고, 2~3경기 조합을 분석하는 **스포츠 데이터/확률 분석 플랫폼** MVP입니다. 처음에는 EPL만
다뤘고, 지금은 데이터 provider가 제공하는 **모든 리그**를 지역·나라·리그로 나눠 보여 줍니다.

- 확률은 **통계 모델(Poisson + Elo)** 이 계산합니다. LLM은 확률을 정하지 않습니다(설명/구조화는 Phase 3).
- 같은 모델을 **리그마다 그 리그의 결과로만** 따로 학습합니다. 컵 대회는 여러 리그 팀이 섞여 있어
  예측하지 않습니다.
- 모델 성과는 실제 경기 walk-forward 백테스트로 측정했습니다: EPL 8시즌(3,040경기) 상세 평가 + 10개 리그
  리그별 채점([MODEL_EVALUATION](docs/MODEL_EVALUATION.md)). 측정한 리그만 "정확도 검증됨"으로 표시하고,
  mock 데이터 결과는 성과 근거로 쓰지 않습니다.
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

API 컨테이너는 시작할 때 `alembic upgrade head`를 실행하고, 로컬 compose에서는 seed(첫 수집)를
**백그라운드로** 실행합니다. API는 바로 켜지고, 전체 리그 첫 수집은 몇 분 걸릴 수 있습니다(`make logs`에서
`[entrypoint] seed finished` 확인). 둘 다 idempotent합니다. 샘플 데이터를 다시 만들거나 갱신하려면 아래 명령을 씁니다.

```bash
make seed        # = docker compose exec api python -m edge_ingestion.cli seed
make smoke       # 실행 중인 스택 end-to-end 점검
make down        # 정지 (DB 볼륨 유지) / 완전 초기화: docker compose down -v
```

`seed`는 몇 번을 실행해도 중복 행을 만들지 않습니다. 시간이 흘러 새 배당 스냅샷이나 결과가 생기면
그 부분만 **추가(append)** 됩니다.

## 항상 켜진 개인 서버 (나만 보기)

맥북을 꺼도 24시간 수집하고 내 기기에서만 여는 방법은 [서버 가이드](docs/SERVER.md)에 있습니다(클라우드 서버 1대 +
Tailscale, 인터넷 공개 없음).

## 다른 PC에서 보기 (GitHub Codespaces)

설치 없이 브라우저만으로 전체 앱을 띄웁니다(회사 PC, Windows 등). 주소는 기본이 **비공개**라 내
GitHub 계정으로 로그인해야만 열립니다.

1. (실데이터를 볼 때만) GitHub → Settings → Codespaces → **Secrets**에서 `API_FOOTBALL_KEY`를 추가하고,
   Repository access에 이 저장소를 고릅니다. 키를 넣지 않으면 데모(mock) 데이터로 뜹니다.
2. 저장소 페이지 → **Code → Codespaces → Create codespace on <브랜치>**.
3. 처음에는 이미지 빌드에 몇 분 걸립니다. 터미널에 `stack is starting`이 나오면 아래 **PORTS** 탭에서
   **3000 (Web)** 의 지구본 아이콘을 누릅니다. API 문서는 8000 포트의 `/docs`입니다.
4. 다 쓰면 왼쪽 아래 Codespaces 메뉴 → **Stop Current Codespace**. 30분 동안 쓰지 않아도 자동으로
   멈춥니다. 멈춰도 DB 데이터는 남고, 다시 열면 자동으로 다시 뜹니다.

- 무료 사용량이 매달 정해져 있습니다(GitHub Settings → Billing에서 확인).
- Codespace가 켜져 있는 동안만 데이터를 수집합니다. 매일 빠짐없는 기록이 필요하면 항상 켜진 배포가
  필요합니다([TODO](docs/TODO.md)).
- 키를 나중에 추가했다면 Codespace를 다시 시작하거나 터미널에서 `bash .devcontainer/start.sh`를
  실행합니다. 키는 환경 변수로만 전달되고 파일에 저장되지 않습니다.
- 포트 공개 범위를 Public으로 바꾸지 마세요. 그러면 주소를 아는 누구나 볼 수 있습니다.

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
| `api_football` | `API_FOOTBALL_KEY` | 플랜의 모든 리그(또는 `API_FOOTBALL_LEAGUES`로 고른 리그) 일정·결과·1X2 배당. [가이드](docs/providers/api-football.md) |

```bash
# .env 에 DATA_PROVIDER=api_football, API_FOOTBALL_KEY=... 설정 후
make check-provider     # DB에 쓰지 않고 키와 응답 형식 검증 (약 6~8 요청)
make up                 # = GIT_SHA=<현재 커밋> docker compose up -d --build
```

실데이터 운영은 `make up`(또는 `GIT_SHA=$(git rev-parse --short=12 HEAD) docker compose up -d --build`)으로
띄웁니다. 그래야 예측의 모델 버전과 오늘의 픽 기록에 빌드 커밋이 남습니다. 커밋 없이 띄우면 `unknown`으로
기록되지만, 코드 지문(`/health`의 `code_fingerprint`)은 항상 남습니다. 어느 커밋인지는 체크아웃에서
`uv run edge code-fingerprint`로 같은 지문을 찾아 맞춥니다(ADR-023).

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
| GET | `/leagues?days=7` | 리그 목록(지역 → 나라 → 리그), 경기 수, 예측·검증 여부 |
| GET | `/leagues/{id}` | 리그 한 개 |
| GET | `/fixtures?date=YYYY-MM-DD&days=1..14&tz=Asia/Seoul` | 기간 내 경기 + 최신 배당/공정확률/모델확률 요약. `league_id`, `country`, `region`, `featured` 필터 |
| GET | `/fixtures/{id}` | 경기 상세 + 배당 스냅샷 이력 |
| GET | `/fixtures/{id}/simulation?runs=10000&seed=` | 최신 예측의 기대 득점으로 경기를 여러 번 다시 치른 결과(스코어·골 합계·양 팀 득점, 한 경기 다시보기). 새 정보는 더하지 않음 |
| GET | `/fixtures/{id}/prediction` | 최신 예측 snapshot: 모델확률, 공정확률, overround, Edge, EV, as-of 시각, 모델 버전 |
| POST | `/combinations/analyze` | 서로 다른 경기 2~3개 selection 조합 (`method: independence_approximation`) |
| GET | `/highlights?days=7&limit=3` | 분석이 시장보다 가장 높게 보는 결과(주의 표시 포함, 추천 아님) |
| GET | `/picks/today` | 오늘(KST)의 픽: 선정 시각에 한 번 고정된 결과, 근거·데이터 점검·백테스트 요약 |
| GET | `/picks/history?limit=60` | 지난 픽(선정 당시 값 보존) + 적중률·Wilson 범위·평균 확률·표본 수 |
| GET | `/review?date=YYYY-MM-DD` | 지난 하루 복기: 경기 전 분석·시장 1순위·결과, 기대 적중 수 대 실제 적중 수 (기본: 어제, KST) |
| GET | `/performance` | 실데이터 walk-forward 백테스트 지표 + 저장된 예측의 실시간 모델 vs 시장 채점 |
| GET | `/status/data` | 마지막 수집 성공/실패, 데이터 신선도 |

```bash
curl -s localhost:8000/fixtures?days=7 | jq '.fixtures[0]'
curl -s -X POST localhost:8000/combinations/analyze -H 'Content-Type: application/json' \
  -d '{"selections":[{"fixture_id":1,"outcome":"HOME"},{"fixture_id":2,"outcome":"DRAW"}]}'
```

## 오늘의 픽 (Today's Pick)

하루(KST)에 최대 한 경기, **데이터 점검을 통과한 오늘 경기 중 분석 확률이 가장 높은 결과 하나**를
보여 줍니다. 추천이나 보장이 아니라 "모델이 가장 확신하는 결과"에 대한 설명입니다.

- 선정 시각(`PICK_PUBLISH_HOUR`, 기본 09:00 KST)에 한 번 정해지고 `daily_picks`에 고정됩니다. 후보는 그때부터
  **다음 날 같은 시각까지** 시작하는 경기입니다(유럽 저녁 경기 포함). 자정~선정 시각 사이에는 전날 아침에 고른 픽이 계속 보입니다
  (append-only, `INSERT ... ON CONFLICT DO NOTHING`). 새로고침·재시작·동시 요청에도 바뀌거나 중복되지
  않습니다.
- 기준 확률(`PICK_MIN_PROBABILITY`, 기본 0.55)은 실데이터 백테스트에서 정했습니다
  ([MODEL_EVALUATION](docs/MODEL_EVALUATION.md)). 못 넘으면 그날은 "픽 없음"입니다.
- 후보는 **정확도가 검증된 리그**의 경기뿐입니다(`PICK_LEAGUES=verified`, `all`이나 리그 id 목록도 가능).
  같은 규칙을 검증된 10개 리그에 서비스와 같은 시점(오전 9시 선정, 다음 날 오전 9시까지의 경기)으로 적용한 백테스트: 0.55에서 647일 중 503일(78%)에 픽, 적중률 74.6% [70.6, 78.2].
- 데이터 점검: 경기 시작 전, 최근 수집 성공(`INGEST_MAX_AGE_HOURS`), 현재 모델 버전, 확률 정상, 배당
  최신(`ODDS_MAX_AGE_HOURS`), 두 팀 경기 기록(`MIN_TEAM_MATCHES`).
- 경기가 취소·연기되면 "무효"로 남기고 적중률에서 뺍니다. 교체 픽은 `PICK_REPLACE_ON_VOID=true`일 때만.
- mock 데이터의 픽은 `is_demo=true`로 저장되고 화면에 데모로 표시됩니다.

| 화면 | 내용 |
| --- | --- |
| `/` | 맨 위에 오늘의 픽 카드, 데이터 신선도 배지, 리그별로 묶은 경기 목록(주요 리그/전체 리그) |
| `/leagues`, `/leagues/[id]` | 지역·나라별 리그 목록과 검색, 리그별 일정 |
| `/picks` | 지난 픽 이력과 요약 |
| `/review` | 경기 복기: 날짜별 경기 전 분석과 결과 (`edge review --date` 로 터미널에서도) |
| `/performance` | 모델 성과(지표·보정 그래프·시즌별·픽 규칙 백테스트) |

## 선발 명단과 결장 정보

- 결장·출전 불투명 선수(경기 2일 전부터), 공식 선발 명단(킥오프 약 1시간 전, worker가 10분마다 확인), 끝난 경기의
  선수별 출전 시간을 수집해 경기 상세 화면에 보여 줍니다(`TEAM_NEWS_LEAGUES`, 기본: 검증된 리그).
- **분석 확률에는 아직 반영하지 않습니다.** 반영 효과를 잰 실험 결과는
  [MODEL_EVALUATION](docs/MODEL_EVALUATION.md)의 "선발 명단 변수 실험"에 있습니다.

```bash
python -m edge_ingestion.cli backtest-lineups                 # StatsBomb 공개 데이터로 실험
python -m edge_ingestion.cli backfill-appearances --days 420  # API-Football 과거 출전 시간 채우기
python -m edge_ingestion.cli backtest-lineups --source db     # 내 DB 데이터로 같은 실험
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
