# Codex 작업 기록

- 담당: Codex / 모델 검증 채팅
- 날짜: 2026-10-16 KST
- 상태: 병렬 작업 기반 준비, 후보 모델 인계 대기
- 기준 커밋: `36715b2`
- 브랜치: `codex/model-qa-contract`
- 작업 폴더: 기존 `getho`와 분리한 `getho-model-qa`
- 목표: Claude의 피로·휴식 후보를 동일 시점·동일 경기에서 검증할 인터페이스 준비
- 변경 범위: `docs/WORK_HANDOFF.md`, `docs/worklogs/`, 예측 계약 문서/예시, 계약 검사 및 테스트
- 설치: 추가 설치 없음. 계약 검사는 Python 표준 라이브러리만 사용. 기존 NumPy/SciPy/pytest/Ruff 확인
- 검증: `python -m unittest discover -s scripts/qa -p test_prediction_contract.py -v` 4개 테스트 통과(잘못된 입력 11종 subtest 포함). 합성 예시 JSONL 검사 PASS. 추가 Python 2개 파일 Ruff lint/format 통과
- 결과 커밋 식별: 이 파일과 계약 파일을 추가한 커밋 (`git log -1 -- docs/worklogs/CODEX_QA.md`)
- 한계: 합성 자료 테스트이며 실제 피로 변수 모델·정확도 개선은 아직 없음. Claude에 자동 메시지를 보내거나 작업을 시작시키지 않음
- 다음 담당자: Claude가 계약/데이터 가용성을 확인하고 후보 구현 후 자기 기록·결과 커밋을 전달

기존 QA 성과: 기준 모델 재현, ML 테스트 99개 통과, 확률 앙상블 미채택. 자세한 내용은 [기존 보고서](../qa/2026-10-16-model-validation-and-improvement.md).

## 로컬 웹 실행 환경 추가

- 사용자 요청으로 Docker 실행 환경을 설정했다. 이전 Docker 미사용 조건은 이번 로컬 실행 요청에서 변경됐다.
- 기존 Ubuntu WSL에 Docker Engine/Compose/Buildx 설치, 5개 컨테이너 실행, 데모 seed 완료.
- CRLF entrypoint 문제와 WSL 자동 종료를 처리했다. API 외부 포트는 18000, 웹은 3000이다.
- 전체 스모크 테스트 통과 및 브라우저 홈 화면 확인. [실행·중지 안내](../LOCAL_WINDOWS_SETUP.md).
- 변경: `.gitattributes`, `compose.local.yaml`, `scripts/local/stack.ps1`, 로컬 환경 문서. 운영 모델은 그대로다.
