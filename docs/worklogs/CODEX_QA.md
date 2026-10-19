# Codex 독립 QA 작업 기록

## 2026-10-19 — 통계 수집 PR #20 검증 / Codex

- main 22f9b07, PR head dc049ef: 기존 통계 테스트 5 PASS / 독립 부분 응답 복구 1 FAIL.
- 한 팀 통계 520행 저장 후 정상 응답으로 재실행해도 나머지 팀 0행 추가(STAT-1/P1).
- [상세 결과](../qa/2026-10-19-pr20-statistics-review.md). 핵심 변경 Ruff PASS, 실 API 신규 호출 없음.
- 이전 #17~#19 보고서/재현 파일도 함께 QA 브랜치에 보존. 기능 코드 수정 없음.

## 2026-10-19 — Claude #17~#19 후속 검증 / Codex

- main 890a1f3: 관련 회귀 43 PASS. 원본 MORN-1/2/3 해결 재현, populated downgrade PASS.
- #19 리그 이름 충돌 독립 반례 1 FAIL(P2). #18 실제 xG 응답은 미검증.
- [후속 보고서](../qa/2026-10-19-pr17-pr19-followup.md). QA DB만 복구, 기능 소스 변경 없음.
- 추가 DB 조회 자동 승인 서비스 사용량 한도 오류. 진행 중 테스트는 정상 완료.

## 2026-10-19 — 다음 실험 착수 검토 / Codex

- main a55b717 fetch: #15/#16 병합, 검토 head 3a42c18과 tracked tree 동일. 수정 3건은 아직 없음.
- shadow 순수 모델 테스트 5 PASS. 전체 suite/실데이터/배포는 이번에 재실행하지 않음.
- 실제 결정 시각과 09:00, 등록된 일 단위 CI와 요구된 주 단위 검증을 구분하고
  누락일·가용률 중심 관측을 다음 구현으로 제안. [착수 조건](../qa/2026-10-19-next-stage-readiness.md).

## 2026-10-19 — 아침 PR 검증 및 모델 후속 분석 / Codex

- #16 head 3a42c18에서 Python 389 PASS, 웹 100 PASS, lint/typecheck/build/Ruff/계약 PASS.
- 새 독립 반례 3 FAIL: 선수 행 시점 누수, malformed 결장 coverage, shadow 조회 장애 전파.
- [아침 QA 상세](../qa/2026-10-19-morning-pr14-pr16-review.md). 이전 F1~F6/M2/M3는 수정 재검증 PASS.
- 고정 실데이터 manifest 676경기를 paired 재분석. 시장 LL .985904, 혼합 .988995,
  운영 1.011212. 신규 미관측 시험 아님. 1주 표본으로 CI 산출 보류, 모델 교체 불승인.
- 추가 분석 도구 및 테스트 6 PASS. 양 팀 결장 커버리지 34경기, 공식 선발 0경기로
  선수 효과 학습은 보류. [분석 결과와 Claude 구현 순서](../qa/2026-10-19-model-paired-followup.md).
- 담당 Codex: QA 테스트·분석·문서만 변경. Claude 기능 코드·운영 DB·모델 버전 변경 없음.

## 2026-10-19 — Codex

- 후속 실행: 같은 09:00 시장 비교 read-only 도구 구현, 테스트 2 PASS, 실데이터 DB 감사.
  3,364경기 manifest / 943비교 가능 / 676완료; 시장 LL .985904, 운영 1.011212.
  평가 2일·여러 리그·모델 SHA local·과거 후보 집합 부재 때문에 승격 증거로 인정하지 않음.
- 선수 실데이터 726경기 출전 기록, 아침 양 팀 결장 정보 54경기, 공식 선발 0경기, 관측 xG 수집 경로 없음 확인.
- [후속 결과와 Claude 구현 요청](../qa/2026-10-19-next-experiment-readiness.md). 운영 기능은 수정하지 않음.

- main d6cef46 유지. PR #10 `233074cd4d031e71e0c80b5e119b21d45173bf77`, PR #11 `7c972840d03480fe2ca76b68128a5b8c53b09fe7` 독립 worktree에서 검토.
- PR #11 Python 302 / web 96 / lint / typecheck / build PASS. 독립 복기 생성 시각·집계 범위 반례 FAIL.
- PR #10 관련 테스트 8 PASS, 보정 실험 수치 재현. 단조 증가·동일 확률 isotonic 경계 테스트 2 FAIL.
- 기존 F1~F4 재현. 미관측 시험 부재 및 기존 승격 기준 미충족으로 모델 교체 불승인.
- QA 도구·테스트·보고서만 작성, 기능 수정·배포·main 병합 없음.
- [오늘 보고서](../qa/2026-10-19-independent-qa.md). 다음 담당 Claude: F5/F6/M2/M3 및 기존 결함 수정 SHA 제공, M1 새 평가 구간 준비.

## 2026-10-16 — 최초 검토

- 담당: Codex, 2026-10-16 KST.
- 기준: main `2d4b1abb9b8a7cbddc39fa932cee1628492d6723`, PR #4 `b916f2e851c32ac4b759a2acebadfd2423ec8923`.
- 격리: `getho-independent-qa` / `codex/main-ui-independent-qa`, PR 실행용 `getho-pr4-qa`.
- 실행: 원본 Python 255, main 웹 66, PR 웹 84 통과. Docker build/smoke, migrations, 계약,
  EPL 원본 캐시 재평가, Edge 시간대·모바일·취소 응답, 4프로세스 동시 선정 검증.
- 추가 QA 테스트/계약/보고서만 작성. Claude 기능 소스, main, 모델 버전, 기존 실데이터 스택은 변경하지 않음.
- 발견: 선택 이후 예측 갱신 시 배당 무통보 변경, 미래 입력 품질 게이트 통과. 두 반례는 main과 PR #4에서 FAIL.
- 판단: NEEDS_CHANGES, 모델 승격 불승인. [상세 보고서](../qa/2026-10-16-independent-main-pr4.md).
- 다음 담당: Claude가 F1/F2를 수정한 새 PR SHA 제공 → Codex 독립 재검증.
- 과거 기록은 `codex/model-qa-contract`의 같은 경로에 보존. 과거 실데이터 연동 성공을 최신 SHA의 검증으로 전용하지 않음.

## 후속 독립 검토 — Codex, 2026-10-16 KST

- PR #5 최종 head `1d5262e295b95325ca3875351aba3e5a1ca7d212`: 독립 경계 4 FAIL / 3 PASS.
- main `d6cef46c5df38c8b0a444d4aca8e90697be4c1fb`: 기존 Python 296, web 93 PASS.
  독립 반례 6 FAIL / 3 PASS. lint/typecheck/Ruff PASS.
- 추가 발견: 구간 밖으로 옮겨진 픽이 live/finished로 처음 수집되면 무효되지 않음(P1),
  최근 미해결 100개가 반복 재조회를 점유해 오래된 경기가 누락됨(P2).
- 기존 배당 경쟁 조건 및 미래 시각 품질 반례도 재현. input_data_as_of 조회 cutoff 추가는 개선으로 인정.
- 시장 예측 22,671행의 산술 감사 스크립트와 JSON 작성. 후속 9,663경기의 수치는 일치하나
  실제 배당 가용 시각이 없어 09:00 운영 모델 교체는 승인하지 않음.
- 테스트와 보고서만 QA 브랜치에 추가. 기능 소스·운영 스택·모델 버전·main 병합은 변경하지 않음.
- [후속 상세 보고서](../qa/2026-10-16-independent-pr5-and-latest-main.md).
- 다음 담당 Claude: F1~F4 수정 SHA 및 시점 계약 증거 제공. Codex: 새 SHA 기준 재검증.
