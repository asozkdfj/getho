# API-Football 연동 가이드

`DATA_PROVIDER=api_football`로 바꾸면 API-Football(api-sports.io v3)에서 EPL 일정·결과·1X2 배당을
수집합니다. 코드는 `workers/ingestion/edge_ingestion/providers/api_football.py`에 있고, core(DB·모델·API·웹)는
바뀌지 않습니다.

## 1. 설정 (5분)

1. https://dashboard.api-football.com 에서 가입하고 API 키를 발급받습니다(Free: 하루 100 요청).
2. 저장소 루트에 `.env`를 만듭니다(`.env`는 git에서 제외되어 있습니다).
   ```dotenv
   DATA_PROVIDER=api_football
   API_FOOTBALL_KEY=발급받은_키
   PRIMARY_BOOKMAKER=bet365            # 시장 기준 북메이커 (아래 3단계에서 목록 확인)
   PIPELINE_INTERVAL_SECONDS=10800     # 3시간마다 수집 (배당 갱신 주기와 같음)
   ```
3. **DB에 쓰기 전에 키와 응답 형식을 검증합니다.** DB에 아무것도 쓰지 않는 dry run이고 약 6~8 요청을 씁니다.
   ```bash
   make check-provider        # 컨테이너에서 check-provider만 실행 (마이그레이션/seed 생략)
   ```
   출력 예시와 확인할 점은 다음과 같습니다.
   ```json
   {"provider": "api_football", "bookmaker": "bet365",
    "account": {"plan": "Free", "active": true, "requests": {"current": 7, "limit_day": 100}},
    "seasons": [2025, 2026], "teams": 23, "fixtures": 470,
    "fixture_statuses": {"finished": 470, "scheduled": 290}, "upcoming_14d": 18,
    "odds_snapshots": 220, "fixtures_with_primary_bookmaker_odds": 18,
    "bookmakers": ["bet365", "pinnacle", "..."], "requests_used": 7}
   ```
   - `error: ... Free plans do not have access to this season`이 나오면 Free 플랜이 해당 시즌을 지원하지
     않는 것입니다. `API_FOOTBALL_SEASON`을 낮춰 테스트하거나 Pro로 전환합니다.
   - `fixtures_with_primary_bookmaker_odds`가 0이면 `bookmakers` 목록에서 원하는 slug를 골라
     `PRIMARY_BOOKMAKER`를 바꿉니다.
4. 스택을 실행합니다.
   ```bash
   docker compose up -d --build     # 시작 시 seed 1회 + worker가 3시간마다 수집/예측
   ```

mock 데이터와 실데이터는 `provider` 컬럼으로 분리됩니다. 경기 목록, 학습, 예측 모두 현재
`DATA_PROVIDER`의 데이터만 사용합니다. 같은 DB에서 provider를 바꿔도 데이터가 섞이지 않습니다.

## 2. 요청량 (Free 100/일 기준)

| 호출 | 횟수/실행 | 비고 |
| --- | --- | --- |
| `/teams?league=39&season=S` | 2 | 현재 + 직전 시즌(강등 팀 포함) |
| `/fixtures?league=39&season=S&timezone=UTC` | 2 | 학습용 직전 시즌 결과 포함 |
| `/odds?league=39&season=S&bet=1&page=N` | 1~3 | 페이지당 10경기, 킥오프 1~14일 전 경기만 |

한 번 실행에 약 6~8 요청이 듭니다. 3시간 간격(하루 8회)이면 약 60 요청/일로 Free 한도 안에 들어갑니다.
Free 플랜은 분당 약 10회 제한이 있어서 요청 사이에 6.5초 간격을 둡니다
(`API_FOOTBALL_MIN_INTERVAL_SECONDS`, 유료 플랜이면 0.3 정도로 낮추면 됩니다).

## 3. 동작 방식

- **배당 스냅샷:** 응답의 `update`(API-Football이 가격을 갱신한 시각)를 `captured_at`으로 씁니다. 그래서
  같은 가격을 다시 받아도 행이 늘지 않고, 가격이 갱신되면 새 스냅샷이 추가됩니다(append-only).
- **배당 보관 기간:** API-Football은 배당을 약 7일만 보관합니다. 수집을 멈춘 기간의 배당은 되살릴 수 없으니
  worker를 계속 돌려야 합니다.
- **경기 상태 매핑:**

  | API-Football `status.short` | 우리 상태 |
  | --- | --- |
  | TBD, NS | scheduled |
  | 1H, HT, 2H, ET, BT, P, SUSP, INT, LIVE | live |
  | FT, AET, PEN | finished |
  | PST | postponed |
  | CANC, ABD, AWD, WO | cancelled (몰수·부전승 스코어는 학습에서 제외) |

- **오류 처리:** HTTP 429/5xx와 네트워크 오류는 지수 백오프(1s, 2s)로 최대 3회 시도합니다. 401/403과
  응답 본문의 `errors`(HTTP 200으로 옴)는 즉시 실패시키고, 원인 메시지만 출력합니다. API 키는 로그,
  repr, 에러 메시지 어디에도 나오지 않습니다.
- **전송:** stdlib `urllib`를 쓰고 HTTPS만 허용합니다. 테스트는 `edge_ingestion.testing.FakeApiFootball`로
  네트워크 없이 실행됩니다.

## 4. 실제 응답 검증 현황

2026-10-15에 Free 플랜 키로 `make check-provider`(`API_FOOTBALL_SEASON=2024`)를 실행해 확인했습니다.

- [x] Premier League `league` id = 39: 시즌별 380경기(20팀 × 38라운드)
- [x] `/teams`, `/fixtures` 응답 파싱: 2023-24와 2024-25 시즌 760경기, 팀 연결 누락 0
- [x] 경기 상태 매핑, 스코어, 라운드, UTC 변환: 2024-25 38라운드 노팅엄 포레스트(65) 0:1 첼시(49),
      2025-05-25 15:00 UTC로 실제 결과와 일치
- [x] 일일 남은 요청 수 헤더 `x-ratelimit-requests-remaining`, `/status`, 응답 본문의 `errors` 처리
- [x] **Free 플랜은 2022~2024 시즌만 조회할 수 있습니다** (`Free plans do not have access to this season`).
      현재 시즌의 일정과 배당은 유료 플랜(Pro 이상)이 필요합니다.
- [ ] `/odds` 응답 형식: `update` 필드, `bet=1` = "Match Winner"(Home/Draw/Away), 페이지 크기와
      `paging.total`. 지난 시즌 배당은 제공되지 않아서 현재 시즌을 조회할 수 있어야 검증할 수 있습니다.

검증용으로 `API_FOOTBALL_SEASON`을 과거 시즌으로 고정하면, 그 시즌은 수집 범위(오늘 기준 400일 전 ~
30일 후) 밖이라 `fixtures_in_ingest_window`가 0이 됩니다. 정상입니다. 운영할 때는 이 값을 비워 두세요.

## 5. 라이선스 메모

비공개 개발과 검증 단계에서는 추가 조치가 필요 없습니다. 공개 서비스(배당 표시, 광고)로 전환하기 전에
API-Football 약관을 다시 확인하고, 필요하면 서면으로 문의합니다. 자세한 배경은 `docs/TODO.md` #1에
있습니다.
