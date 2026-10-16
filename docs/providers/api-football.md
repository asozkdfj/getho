# API-Football 연동 가이드

`DATA_PROVIDER=api_football`로 바꾸면 API-Football(api-sports.io v3)에서 **플랜이 제공하는 모든 리그**의
일정·결과·1X2 배당을 수집합니다. 코드는 `workers/ingestion/edge_ingestion/providers/api_football.py`에 있고,
core(DB·모델·API·웹)는 provider를 모릅니다.

## 1. 설정 (5분)

1. https://dashboard.api-football.com 에서 가입하고 API 키를 발급받습니다. Free 플랜(하루 100 요청)은
   2022~2024 시즌만 조회할 수 있고 요청 수도 부족해서, 전체 리그는 **Pro 이상**이 필요합니다.
2. 저장소 루트에서 `cp .env.example .env` 후 아래 값을 바꿉니다(`.env`는 git에서 제외되어 있습니다).
   주석은 반드시 별도 줄에 둡니다. docker compose는 `KEY=   # 메모`의 주석을 값으로 읽습니다.
   ```dotenv
   DATA_PROVIDER=api_football
   API_FOOTBALL_KEY=발급받은_키
   # all = 플랜의 모든 리그, 일부만 원하면 리그 id를 쉼표로 (예: 39,140,292)
   API_FOOTBALL_LEAGUES=all
   # 시장 기준 북메이커 (리그를 가장 넓게 다루는 bet365가 기본값)
   PRIMARY_BOOKMAKER=
   # 3시간마다 수집 (배당 갱신 주기와 같음)
   PIPELINE_INTERVAL_SECONDS=10800
   ```
   요청 간격은 응답 헤더의 분당 한도에 맞춰 자동으로 조절됩니다(Free 10/분 → 6.3초, Pro 300/분 → 0.21초).
3. **DB에 쓰기 전에 키와 응답 형식을 검증합니다.** DB에 아무것도 쓰지 않는 dry run이고 약 5~10 요청을 씁니다.
   ```bash
   make check-provider
   ```
   확인할 점: `leagues`(리그 수), `leagues_with_odds`, `busiest_leagues`(오늘·내일 경기가 많은 리그),
   `sampled_fixtures_with_primary_bookmaker`(0이면 `bookmakers` 목록에서 다른 slug를 골라
   `PRIMARY_BOOKMAKER`를 바꿉니다), `requests_left_today`.
4. 스택을 실행합니다.
   ```bash
   docker compose up -d --build     # 시작 시 seed 1회 + worker가 3시간마다 수집/예측
   ```

mock 데이터와 실데이터는 `provider` 컬럼으로 분리됩니다. 같은 DB에서 provider를 바꿔도 섞이지 않습니다.

## 2. 요청량 (전체 리그 기준)

| 호출 | 횟수/실행 | 비고 |
| --- | --- | --- |
| `/leagues?current=true` | 1 | 리그 목록, 형식(리그/컵), 현재 시즌, 배당 제공 여부 |
| `/fixtures?date=D&timezone=UTC` | 약 12 | 하루치 **모든 리그** 경기가 한 번에 옴. 3일 전 ~ 8일 후 |
| `/odds?date=D&bet=1&page=N` | 날짜별 페이지 수 | 페이지당 10경기, 앞으로 3일(`ODDS_LOOKAHEAD_DAYS`). 필요한 경기를 다 찾으면 멈춤 |
| `/injuries?date=D` | 약 2 | 앞으로 48시간 경기의 결장·불투명 선수(검증된 리그) |
| `/fixtures?ids=a-b-…` | 20경기당 1 | 선발 명단(킥오프 90분 전부터, 10분마다) + 끝난 경기의 선수별 출전 시간(실행당 200경기) |
| `/fixtures?ids=a-b-…` (밀린 경기) | 보통 0, 20경기당 1 | 킥오프 4시간이 지났는데 아직 예정/진행 중이고, 이번 날짜 조회에 다시 나오지 않은 경기(최근 30일, 실행당 최대 100경기). 다른 날로 옮겨진 경기를 찾습니다 |
| `/fixtures?league=L&season=S` | 리그당 2 | 과거 결과(현재 + 직전 시즌). **리그마다 한 번만**, 실행당 최대 40개 리그 |

- 날짜 단위로 받기 때문에 리그 수가 늘어도 일정 요청은 거의 늘지 않습니다. 배당은 경기 수에 비례합니다
  (주말 하루 수백 경기면 수십 페이지).
- 처음 며칠은 과거 결과 채우기(backfill)로 요청이 더 듭니다. 주요 리그부터 채우고, 채워지기 전까지 그 리그는
  "분석 준비 중"으로 표시됩니다(`BACKFILL_LEAGUES_PER_RUN`).
- 오늘 남은 요청이 `API_FOOTBALL_MIN_REMAINING`(기본 300) 아래로 내려가면 backfill과 남은 배당 페이지를 다음
  실행으로 미룹니다. 경기 일정·결과 갱신은 계속합니다.
- Pro(7,500/일), 3시간 간격이면 보통 하루 수백~2천 요청 정도입니다. 실제 사용량은 `requests_left_today`와
  `/status/data`의 수집 기록(`ingestion_runs.counts.ingestion.requests`)으로 확인합니다.

## 3. 동작 방식

- **리그별 분석:** 같은 모델을 리그마다 그 리그 결과로만 따로 학습합니다. **컵 대회(type=Cup)는 예측하지
  않습니다**(서로 다른 리그 팀이 섞여 한 리그의 전력표로 설명할 수 없음). 배당 정보가 없는 리그와 과거 결과가
  30경기 미만인 리그도 예측하지 않습니다.
- **정확도 검증:** 과거 실데이터로 백테스트한 10개 리그만 "정확도 검증됨"으로 표시하고 오늘의 픽 후보로
  씁니다(`PICK_LEAGUES=verified`, [MODEL_EVALUATION](../MODEL_EVALUATION.md)). 나머지 리그는 분석은 하되
  "검증 전"으로 표시합니다.
- **시즌 표기:** `/leagues`의 시즌 시작·종료 연도로 판단해 유럽식은 `2026-27`, 단일 연도 리그(K리그,
  J리그, MLS 등)는 `2026`으로 저장합니다. 승격팀 처리에 시즌 구분이 쓰입니다.
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
- **실패 범위:** 리그·경기·배당 수집이나 예측에서 오류가 나면 실행 전체를 되돌리고(부분 저장 없음)
  `ingestion_runs`에 `failed`로 따로 기록합니다. 팀 뉴스(결장·선발 명단·출전 시간)는 부가 정보라서, 여기서 난
  provider 오류는 팀 뉴스 저장만 되돌리고 나머지(경기·배당·예측·픽)는 그대로 진행합니다. 오류 내용은
  `ingestion_runs.counts.team_news.error`에 남습니다.
- **밀린 경기:** 일정이 다른 날로 바뀐 경기는 원래 날짜 조회에 더 이상 나오지 않아, 예전 킥오프 시각의
  "예정" 상태로 남을 수 있습니다. 킥오프 4시간이 지나도 예정/진행 중이면 `/fixtures?ids=`로 현재 상태를 다시
  받아 갱신합니다(`fixtures_reconciled`). provider가 돌려주지 않는 경기는 추측하지 않고 그대로 두며 개수만
  기록합니다(`overdue_unresolved`). 그 경기에 걸린 오늘의 픽은 경기가 픽 시간대 밖으로 옮겨지면 "경기 일정
  변경"으로 무효 처리합니다(원래 픽 행은 그대로 보존).
- **입력 검증:** 배당이 1.0 이하이거나 NaN/무한대인 행, 모르는 경기의 배당은 버리고 `odds_rejected`로
  셉니다. 상태가 잘못됐거나 모르는 리그, 같은 팀끼리인 경기는 건너뛰고, 같은 경기 id가 두 번 오면 마지막 것만
  씁니다.
- **전송:** stdlib `urllib`를 쓰고 HTTPS만 허용합니다. 테스트는 `edge_ingestion.testing.FakeApiFootball`로
  네트워크 없이 실행됩니다.

## 4. 실제 응답 검증 현황

2026-10-15에 Free 플랜(시즌 2024 고정)과 Pro 플랜(현재 시즌)으로 EPL 단일 리그 버전의 `make check-provider`를
실행해 확인한 항목입니다.

- [x] Premier League `league` id = 39: 시즌별 380경기(20팀 × 38라운드)
- [x] `/teams`, `/fixtures` 응답 파싱: 2023-24와 2024-25 시즌 760경기, 팀 연결 누락 0
- [x] 경기 상태 매핑, 스코어, 라운드, UTC 변환: 2024-25 38라운드 노팅엄 포레스트(65) 0:1 첼시(49),
      2025-05-25 15:00 UTC로 실제 결과와 일치
- [x] 일일 남은 요청 수 헤더 `x-ratelimit-requests-remaining`, `/status`, 응답 본문의 `errors` 처리
- [x] **Free 플랜은 2022~2024 시즌만 조회할 수 있습니다** (`Free plans do not have access to this season`).
      현재 시즌의 일정과 배당은 유료 플랜(Pro 이상)이 필요합니다.
- [x] `/odds` 응답 형식(Pro 플랜, 2026-27): `update` 필드, `bet=1` = "Match Winner"(Home/Draw/Away),
      페이지 처리. 앞으로 14일 20경기 중 19경기에 배당, 10개 북메이커(1xbet, bet365, betano, betfair,
      betvictor, dafabet, marathonbet, pinnacle, sbo, williamhill)에서 174개 스냅샷을 파싱했습니다.

**전체 리그 버전에서 새로 쓰는 호출은 아직 실제 응답으로 확인하지 않았습니다**(개발 환경에서 해당 도메인이
차단됨). 경기·배당 항목의 형식은 위에서 확인한 것과 같고, 차이는 조회 방식뿐입니다.

- [ ] `/leagues?current=true`: `league.type`(League/Cup), `country`, `seasons[].current/start/end/coverage.odds`
- [ ] `/fixtures?date=`: 여러 리그 경기가 한 응답에 오는지, `league.id/season/round`
- [ ] `/odds?date=`: 날짜 단위 페이지 처리
- [ ] 분당 한도 헤더 `x-ratelimit-limit`
- [ ] `/injuries?date=`: `player.type`("Missing Fixture"/"Questionable"), `reason`, `fixture.id`
- [ ] `/fixtures?ids=`: `lineups[].startXI`, `players[].players[].statistics[0].games.minutes`
- [ ] `/fixtures?ids=`로 받은 경기 객체가 날짜 조회와 같은 형식인지(밀린 경기 갱신에 사용), 옮겨진 경기의
      새 `fixture.date`와 `status.short`(TBD/NS/PST)

`make check-provider` 결과의 `leagues`, `busiest_leagues`, `odds_snapshots_sampled`가 0이 아니면 확인된 것입니다.

## 5. 라이선스 메모

비공개 개발과 검증 단계에서는 추가 조치가 필요 없습니다. 공개 서비스(배당 표시, 광고)로 전환하기 전에
API-Football 약관을 다시 확인하고, 필요하면 서면으로 문의합니다. 자세한 배경은 `docs/TODO.md` #1에
있습니다.
