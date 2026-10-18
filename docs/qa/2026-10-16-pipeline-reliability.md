# 실데이터 파이프라인 신뢰성 점검 (2026-10-16)

대상: `workers/ingestion` 수집 파이프라인(API-Football)과 오늘의 픽 정산.
모델과 예측 확률은 바꾸지 않았습니다.

## 검증 범위: 무엇으로 확인했나

| 구분 | 방법 | 이번 점검 |
| --- | --- | --- |
| 오프라인 테스트 | `FakeApiFootball`(문서 형식의 합성 응답), `MockProvider`, 로컬 Postgres | 아래 표의 모든 항목 |
| 실제 API 호출 | `make check-provider`, 실제 키로 파이프라인 실행 | **하지 않았습니다.** 이 환경에는 API 키가 없습니다. 실제 응답 확인은 [가이드 §4](../providers/api-football.md#4-실제-응답-검증-현황)와 TODO #23·#26·#33에 남아 있습니다 |

오프라인 테스트는 "우리 코드가 이 형식의 응답을 이렇게 처리한다"는 것만 보여줍니다. 실제 API가 그 형식과
상황(예: 옮겨진 경기를 `ids` 조회로 돌려주는지)대로 응답하는지는 실제 호출로 확인해야 합니다.

## 실패 상황별 처리와 테스트

| 상황 | 이전 동작 | 지금 동작 | 테스트 |
| --- | --- | --- | --- |
| 경기가 다른 날로 옮겨짐(날짜 조회 범위 밖) | 예전 킥오프 시각의 "예정"으로 남음. 그 경기의 픽은 정산·무효가 안 됨 | 킥오프 4시간 뒤에도 예정/진행 중이면 `/fixtures?ids=`로 다시 받아 갱신 | `test_overdue_fixture_moved_out_of_the_window_is_looked_up_by_id`, `test_ingestion_run_reconciles_and_reports` |
| provider가 그 경기를 더 이상 돌려주지 않음 | 위와 같음 | 상태를 추측하지 않고 그대로 두며 `overdue_unresolved`로 기록 | `test_overdue_fixture_the_provider_no_longer_returns_is_reported` |
| 요청 한도가 거의 소진됨 | (해당 없음) | 밀린 경기 조회를 다음 실행으로 미룸(요청 0) | `test_overdue_lookup_waits_when_the_budget_is_low`, `test_fixtures_by_ids_stop_when_the_budget_is_low` |
| 밀린 경기가 한 번 조회 한도(100)보다 많고 일부가 계속 응답 없음 | (Codex QA F4) 같은 최근 경기만 반복 조회, 나머지는 영영 안 물음 | 마지막 조회 시각 순으로 순환(`reconcile_checked_at`, ADR-022) | `test_unresolved_fixtures_do_not_starve_the_rest_of_the_backlog` |
| 30일보다 오래된 미해결 경기 | (해당 없음) | 다시 묻지 않음(요청 낭비 방지) | `test_old_and_finished_fixtures_are_not_reconciled` |
| 픽의 경기가 픽 시간대 밖으로 옮겨짐 | 정산 안 됨 | "fixture rescheduled" 무효 이벤트 1회 추가, 원래 픽 행 보존. 같은 날 안에서 시각만 바뀌면 그대로 유효. 다음 수집에서 이미 진행 중·종료로 보여도 무효가 먼저(Codex QA F3, ADR-022) | `tests/integration/test_picks.py::test_pick_on_a_rescheduled_match_is_voided`, 웹 `voidReasonText` |
| 연기·취소 | 무효 처리 | 그대로 | 기존 `test_settlement_and_voiding_are_appended_once` |
| 몰수(AWD)·부전승(WO) | 취소로 매핑, 스코어 없음 | 그대로(WO 테스트 추가) | `test_history_parsing_and_status_mapping`, `test_walkover_is_cancelled_without_a_score` |
| 팀 뉴스(결장·명단) 수집 중 provider 오류 | 실행 전체가 되돌려짐(경기·배당·예측·픽까지) | 팀 뉴스만 되돌리고 나머지 진행, 오류는 `counts.team_news.error`에 기록 | `test_team_news_provider_error_keeps_the_rest_of_the_run` |
| 경기·배당 수집 중 provider 오류 | 실행 전체 되돌림 + 실패 기록 | 그대로(테스트 추가: 부분 저장 0, `failed` 실행 1건) | `test_failed_run_writes_nothing_and_is_logged` |
| 잘못된 배당(≤1.0, 0, NaN, 무한대), 모르는 경기의 배당 | 버림 | 그대로(테스트 추가) | `test_invalid_prices_and_unknown_fixtures_are_rejected` |
| 중복 경기 id, 같은 팀끼리, 모르는 리그, 잘못된 상태 | 건너뜀/마지막 것 사용 | 그대로(테스트 추가) | `test_invalid_fixture_rows_are_skipped_and_duplicates_collapse` |
| 같은 데이터 재수집 | 변경 0 | 그대로(밀린 경기 조회도 0) | `test_rerun_does_not_rewrite_existing_fixtures`, 기존 멱등성 테스트 |
| 오래된 배당·오래된 수집 | 픽 품질 검사(`odds_fresh`, `ingestion_recent`)에서 제외 | 그대로 | 기존 `test_stale_data_blocks_the_pick` |
| 선수 정보 누락(명단 11명 미만, 출전 시간 없음) | 저장하지 않음 | 그대로 | 기존 `test_team_news.py` |

## 요청량 영향

- 정상 상황에서는 밀린 경기가 없어서 추가 요청이 0입니다(기존 `test_pipeline_with_api_football_is_idempotent`의 `/fixtures` 호출 수 검사가 그대로 통과).
- 일정이 바뀐 경기가 있으면 20경기당 1요청, 실행당 최대 100경기(5요청)입니다.
- 요청 한도 보호(`API_FOOTBALL_MIN_REMAINING`)를 그대로 따릅니다.

## 남은 위험

- 실제 API가 옮겨진 경기를 `ids` 조회에서 새 날짜·`NS`/`TBD`로 돌려주는지 확인하지 않았습니다. 다르게 오면
  `overdue_unresolved`가 늘어나는 것으로 드러납니다(조용히 잘못 갱신하지는 않음).
- 픽 시간대 정보(`evidence.window_utc`)가 없는 아주 오래된 픽은 일정 변경 무효 처리가 적용되지 않습니다.
- 수집 실패 알림 채널은 아직 없습니다(TODO #34).
