# 의사결정 기록 (ADR-lite)

각 항목: 옵션 → 선택 → 이유. 바꾸고 싶으면 해당 ADR을 갱신하고 영향 범위를 확인합니다.

## ADR-001 Python 패키지 경계

- 옵션: (a) 단일 패키지 (b) uv workspace 3개 패키지 `edge_ml / edge_api / edge_ingestion` (c) 서비스별 repo
- **선택: (b)**. `ml`은 DB와 HTTP에 의존하지 않아 독립적으로 테스트할 수 있고, ingestion은 API의 ORM을
  재사용합니다. lockfile은 하나(`uv.lock`)이고 Docker 이미지도 하나입니다. 나중에 DB 레이어를
  `packages/db`로 빼면 ingestion을 별도 서비스로 분리할 수 있습니다.
- 편차: 기획서 트리의 `infra/migrations/` 대신 마이그레이션을 `apps/api/migrations/`에 둡니다. ORM
  모델과 같은 패키지에 있어야 autogenerate와 `alembic check`가 단순해지기 때문입니다.

## ADR-002 odds_snapshots 형태

- 옵션: (a) selection당 1행(`selection, odds`) (b) 한 북메이커의 1X2 세트를 1행으로 (c) 헤더 + 가격 child 테이블
- **선택: (b)**. de-vig는 세트 단위로 해야 하고, `market_odds_snapshot_id` 하나로 예측이 쓴 가격 세트를
  정확히 가리킬 수 있습니다. O/U 같은 다른 시장이 추가되면 (c)로 확장합니다(`market` 컬럼은 이미 있음).

## ADR-003 Mock 일정 앵커링

- 옵션: (a) 고정 날짜 seed (b) 실행일 기준 상대 날짜 (c) 고정 4일 그리드에 앵커링한 상대 날짜
- **선택: (c)**. 언제 실행해도 오늘과 이번 주에 경기가 있고, 같은 4일 창 안에서는 결과가 바이트 단위로
  동일해 seed가 idempotent합니다. 창이 바뀌면 mock이 시즌을 "재일정"합니다. fixtures는 upsert로
  갱신되고 새 배당 스냅샷이 추가되는데, 실제 provider의 일정 변경과 같은 경로입니다. 일정은 4일마다 한
  라운드, 하루 2~3경기로 실제 EPL 패턴과 다릅니다(데모 목적).

## ADR-004 prediction 멱등 키

- 옵션: (a) 같은 날 1회 (b) `(fixture, model_version)` 최신 1개 덮어쓰기 (c) `(fixture, model_version, odds_snapshot, input_data_as_of)` append
- **선택: (c)**. 덮어쓰기는 금지 조건(과거 값 보존)을 어깁니다. 입력 데이터 시각을 키로 쓰면 재실행은
  no-op이 되고 입력이 바뀌면 새 snapshot이 쌓입니다.

## ADR-005 Elo와 Poisson 결합

- 옵션: (a) Poisson만 (b) 확률 수준에서 가중 평균(Elo에는 무승부 모델이 별도로 필요) (c) 골 득실 우위(supremacy) 수준에서 결합
- **선택: (c)**. 결과가 여전히 하나의 score matrix에서 나오므로 1X2 합이 1이고, O/U 같은 시장으로도
  확장할 수 있습니다. 가중치 0.6과 280 Elo/골은 초기값이며, Phase 2 walk-forward 검증에서 튜닝합니다.

## ADR-006 Web → API 통신

- 옵션: (a) 브라우저가 API 직접 호출(CORS, public URL) (b) 서버 컴포넌트 + same-origin proxy route
- **선택: (b)**. API 호스트를 비공개로 둘 수 있고, 이미지 하나로 모든 환경에 배포할 수 있습니다
  (런타임 env). 확률이 stale하게 캐시되지 않도록 `cache: "no-store"`를 씁니다.

## ADR-007 Next.js 버전

- Next 15.5는 번들된 postcss 취약점(GHSA, high)이 있어, 패치된 **Next 16.4**와 vitest 5를 씁니다.
  `next lint`가 제거된 버전이라 ESLint flat config(`eslint-config-next`)를 직접 실행합니다.

## ADR-008 시장 기준선 de-vig 방법

- 옵션: proportional, power, Shin
- **선택: proportional** (MVP). 투명하고 설명하기 쉽습니다. favourite-longshot bias를 보정하는 Shin과
  power는 `DevigMethod` enum으로 확장할 예정입니다(TODO).

## ADR-009 API-Football provider 구현 방식

- **HTTP 클라이언트:** (a) httpx/requests 의존성 추가 (b) stdlib urllib + 주입 가능한 transport → **(b)**.
  의존성을 늘리지 않고, 테스트는 녹화 형식 payload로 오프라인 실행합니다.
- **배당 `captured_at`:** (a) 수집 시각(벽시계) (b) 응답의 `update` 필드 → **(b)**. (a)는 같은 가격을
  받을 때마다 중복 스냅샷을 만들어 idempotency를 깨뜨립니다.
- **배당 조회 단위:** (a) 경기별 `/odds?fixture=` (b) 리그+시즌 페이지 조회 → **(b)**. 경기 20개 기준으로
  요청이 20회에서 2회로 줄어 Free 한도에서도 운영할 수 있습니다.
- **provider 간 데이터 격리:** 목록, 학습, 예측을 `fixtures.provider = DATA_PROVIDER`로 한정합니다. 합성
  데이터가 실데이터 모델을 오염시키지 않게 하기 위해서입니다.
- **몰수(AWD)·부전승(WO):** `cancelled`로 매핑하고 스코어를 버립니다. 행정 스코어는 팀 강도와 무관합니다.

## ADR-010 승격팀 prior (모델 v0.2.0)

- 문제: 실데이터에서 승격팀(Hull City, Ipswich)이 리그 평균(Elo 1500, 공격/수비 1.0)에서 출발해 크게
  과대평가됐습니다(예: Fulham–Hull 원정 승 모델 37% vs 시장 20%).
- 옵션: (a) 승격팀을 강등권 수준에서 출발 (b) Championship 데이터를 추가하고 리그 간 수준 차이로 환산
  (c) 경고 표시만 → **(a)**. 축구 모델에서 흔히 쓰는 방법이고 코드 변경이 작으며 근거를 설명하기 쉽습니다.
  (b)는 정확도를 더 높일 여지가 있어 Phase 2 후보로 남깁니다.
- 기준: 직전 시점 하위 3팀(강등 슬롯 수)의 평균. 시즌 정보가 없거나 한 시즌뿐이면 이전 동작(리그 평균)을
  유지합니다. 승격·강등이 없는 데이터에서는 v0.1.0과 결과가 같습니다(테스트로 보장).
- 출력이 바뀌므로 `MODEL_VERSION`을 0.2.0으로 올렸습니다. 기존 v0.1.0 예측은 보존되고 새 예측이 따로
  쌓입니다.
