# 오늘의 픽 신뢰성 점검 (2026-10-16)

대상: `apps/api/edge_api/services/picks.py`(선정·고정·정산·기록), `/picks/today`, `/picks/history`, 지난 픽 화면.
모델과 예측 확률, 선정 규칙은 바꾸지 않았습니다. 실제 API는 호출하지 않았습니다(Mock 데이터와 로컬 Postgres).

## 요구사항별 점검

| 요구사항 | 점검 결과 | 근거(테스트) |
| --- | --- | --- |
| 픽 하루 = 09:00 KST → 다음 날 09:00 | 유지 | `test_pick_day_runs_from_the_publish_hour_to_the_next_morning` |
| 선정 시점에 사용 가능한 데이터만 사용 | **보완**: 후보 예측을 입력 시각(`input_data_as_of`) ≤ 결정 시각으로 제한. 이전에는 결정 시각 뒤에 만든 예측도 쓸 수 있었음(고정 시계·재실행) | `test_decision_only_sees_predictions_known_at_decision_time` |
| 선정 이후 공개된 라인업 사용 금지 | 해당 없음: 운영 모델(v0.2.0)은 라인업을 쓰지 않음(라인업 변수 미채택, ADR-014) | — |
| 원본 픽·확률·모델 버전·데이터 시점·정책 버전 보존 | **보완**: `policy.version`, `evidence.decided_at`, `evidence.last_collection_at` 추가. 나머지는 이미 보존(append-only 트리거) | `test_decision_time_and_policy_version_are_recorded`, `test_daily_picks_are_append_only` |
| 재실행이 과거 픽을 바꾸지 않음 | 유지: (provider, 날짜, revision) 유일 키 + ON CONFLICT DO NOTHING, 수정·삭제 금지 트리거 | `test_publication_is_idempotent`, `test_daily_picks_are_append_only` |
| 품질이 나쁘면 강제로 고르지 않음 | 유지: 품질 검사 실패·기준 확률 미달이면 "고르지 않음" | `test_stale_data_blocks_the_pick`, `test_no_qualifying_match_when_threshold_is_unreachable` 등 |
| 시뮬레이션 성과와 실제 성과 분리 | **보완**: 지난 픽 성과는 경기 시작 전에 기록된 픽만 셈. 이전에는 경기 후 기록된 픽도 섞일 수 있었음. 백테스트 수치는 별도(`evidence.backtest`), 데모는 배너로 구분 | `test_live_record_counts_only_picks_written_before_kickoff`, 웹 `historySummaryText` |

변이 확인: 결정 시각 필터를 지우면 `test_decision_only_sees_predictions_known_at_decision_time`가, 성과 조건을
지우면 `test_live_record_counts_only_picks_written_before_kickoff`가 실패합니다.

## 남은 위험

- 결정 시각 재현은 예측 입력 시각 기준입니다. 학습에 쓰는 경기 결과는 "킥오프 시각"으로 판단하므로, 과거
  시각으로 고정해 다시 돌리면 그 시각에 아직 끝나지 않은 경기가 학습에 들어갈 수 있습니다. 실시간 운영에서는
  생기지 않고, 그렇게 만든 픽은 경기 후 기록으로 성과에서 빠집니다.
- 수집 기록은 결정 시각으로 거르지 않습니다(ADR-018). 고정 시계 재실행의 "최근 수집" 검사는 그 뒤의 수집을 볼 수
  있습니다.
- 지난 픽 성과는 정책 버전·모델 버전을 나누지 않고 합칩니다. 실데이터 픽이 쌓이고 정책이나 모델이 바뀌면 나눠서
  보여 줘야 합니다(TODO #35).
