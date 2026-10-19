# PR #20 통계 수집 독립 QA — Codex, 2026-10-19

판정: **NEEDS_CHANGES**. 새 수집 기능의 부분 응답 복구에서 결함을 재현했다.

- PR: https://github.com/asozkdfj/getho/pull/20
- Base: `890a1f3542af22895b38e31437b0a5008fe110a8`
- Head: `dc049ef5f8c58967362596ced56c7924f9a8c4bf`
- 실행 main: `22f9b074ad11c41dbefe494a97c3630c97cbbf7b`
- 격리 브랜치: `codex/qa-pr20`, Python 3.12.13, 별도 QA PostgreSQL 15432/edge_test_morning.

## 실행

```text
python -m pytest -q workers/ingestion/tests/test_match_statistics.py workers/ingestion/tests/test_codex_partial_statistics.py
1 failed, 5 passed in 48.32s
```

기존 5개는 append-only, 최초 수집 멱등성, 시점 조회, 통계 없는 과거 경기 보강,
동일 API 응답 재사용을 확인한다. 새 독립 반례 1개는 부분 수집 복구를 확인한다.
수집/조회 핵심 변경 파일과 새 테스트 Ruff PASS.
pytest DB 준비에서 migration 0010 적용. 별도 Alembic check/전체 suite/웹/Docker smoke 미실행.
실제 API 신규 호출 및 운영 데이터 쓰기 없음. 기능 소스 수정 없음.

## STAT-1 / P1 — 한 팀 통계만 저장되면 나머지 팀을 다시 수집하지 않음

위치: `workers/ingestion/edge_ingestion/team_news.py`, ingest_post_match의 no_stats 조건.
`~exists().where(MatchStatistic.fixture_id == Fixture.id)`는 통계가 한 행이라도 있으면
해당 경기 수집이 완료된 것으로 취급한다. 선수 출전 기록도 있으면 다음 조회 대상에서 빠진다.

재현 절차:

1. MockProvider로 완료 경기와 선수 기록을 준비한다.
2. 최초 통계 응답은 경기마다 한 팀 행만 반환하게 한다.
3. ingest_post_match 실행: 출전 기록과 한 팀 통계 520행 저장.
4. 공급자 응답을 정상 양 팀 통계로 복구하고 같은 수집 함수를 다시 실행한다.

기대: 누락된 나머지 팀 520행 추가. 실제: **0행** 추가.
단순 재실행으로 회복되지 않는 결측이 후속 xG/슈팅 실험에 남는다.
실제 API에서 520경기의 부분 응답이 발생했다는 뜻은 아니며 독립 합성 반례다.

권장 수정: 해당 경기의 home_team_id/away_team_id 각각의 통계 존재를 확인하고,
한쪽 누락은 재시도 대상으로 남긴다. 영구 미제공과 임시 실패는 구분해 무한 재시도로
다른 경기 수집을 막지 않도록 한다. 같은 경기의 중복/변경 행으로 양 팀 완료 판정을
대신하지 않는다. 선수 출전 기록의 부분 수집도 별도 완료 조건을 검토한다.

재현 파일: `scripts/qa/test_partial_statistics.py`를 검증 대상의
`workers/ingestion/tests/test_codex_partial_statistics.py`로 복사해 대상 conftest로 실행.

## 실제 xG와 모델 판단

새 문서는 사용자가 40경기/10리그 실제 응답에서 양 팀 xG를 확인했다고 기록한다.
이를 사용자 실행 보고로 인정하되 Codex의 독립 실호출 검증으로 표시하지 않는다.
과거 시즌 전체 커버리지와 당시 가용 시각은 별도 증거가 필요하다.
MockProvider xG는 합성 데이터이므로 예측력 실험 증거로 사용할 수 없다.

앞선 CQ-1 리그 이름 합산 결함은 이번 PR의 변경 범위 밖이고 수정되지 않았다.
새 모델 학습·성능 향상·운영 모델 교체는 이번 PR에서 구현하거나 승인한 사항이 아니다.
다음: STAT-1/CQ-1 수정 → 실제 수집 커버리지·시점 확인 → 후보 사전 등록 및 paired 평가.
