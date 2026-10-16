# Codex 독립 QA 작업 기록

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
