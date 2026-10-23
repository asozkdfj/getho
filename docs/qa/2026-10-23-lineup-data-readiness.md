# 선수 실험 데이터 준비 상태 확인

2026-10-23 / Codex. 사용자 요청: 다음 단계 2번(시즌별 데이터·명단 누락·중복·과거 이력·시각) 확인.

**판정: INCONCLUSIVE — 실험 원본 CSV 및 운영 readiness 원본 미확보.**

## 확인한 사실

- 작업 공간의 선수 CSV/readiness JSON을 검색했다. 실행 checkout은 숨김·ignore 파일까지 확인했다. 발견한 CSV는 테스트 캐시와 베트맨 예제뿐이며 실제 선수 실험 데이터가 아니다.
- 원격 main은 조회 시 `cd50d21`이며, #44 CSV 추출 기능과 #45 UI가 있다. 로컬 검토 소스는 #46 `6cb69d50d88f97051b73f65d5775f87a5acfa046`이다.
- 사용자는 파일 위치/추출 여부를 아직 모른다고 답했다. AWS 서버에 실제 파일이 없는 것으로 단정하지 않는다. 서버 접속 주소와 인증된 연결도 현재 확보하지 못했다.
- 문서에는 서버의 검증 10리그/이력 가능 3,676경기, 2025-26·2026-27 두 시즌 및 2023-24~2025-26 CSV 추출 계획이 있다. 이는 개발 측 기록이며 이번 독립 검사 결과가 아니다.
- 운영 API 예산을 소비하는 재추출이나 DB 변경은 수행하지 않았다.

## 현재 항목별 판정

| 검사 | 판정 | 부족한 근거 |
| --- | --- | --- |
| 2023-24, 2024-25, 2025-26 실제 수집 완료 | INCONCLUSIVE | 시즌별 원본 CSV/추출 요약 |
| 경기 수와 전체 경기 누락 | INCONCLUSIVE | 공급자 시즌 전체 fixture ID 목록과 CSV 대조 |
| 양 팀 선발 11명, 명단 누락·중복 | INCONCLUSIVE | 실제 선수 행 |
| 최근 3/10경기 이력과 초기 구간 | INCONCLUSIVE | 시간순 전체 자료와 확정된 history 규칙 |
| 원본 파일 SHA-256 | INCONCLUSIVE | 파일 바이트와 manifest. 이전 Windows 해시 결함 수정 필요 |
| 경기 전 선발 가용 시각 | 현재 CSV만으로 증명 불가 | announced_at/captured_at/created_at/decision_at 없음 |
| 모델 정확도 향상 | 미평가 | 이번 작업은 데이터 검사이며 모델 채점 아님 |

## 준비한 검증 도구

`scripts/qa/audit_lineup_csv.py`는 실제 파일 바이트의 SHA-256, 필수 필드, fixture 메타데이터 충돌, 선수 중복, 타 팀 선수, 비정상 값, 명단 없는 placeholder, 양 팀 11명 여부를 검사한다. 리그·시즌별 집계를 출력한다.

팀별 선행 full XI 3/10경기도 계산하되 **이전 kickoff 기준 대리 집계**로 이름을 명시했다. 동일 kickoff 자료는 서로의 과거 이력에 넣지 않는다. 종료/저장 시각이 없어 실제 가용 이력임을 인증하지 않는다. 자료가 구조적으로 정상이어도 experiment_readiness는 INCONCLUSIVE로 유지한다.

```text
python -m scripts.qa.audit_lineup_csv <실제-선수-CSV> --expected-sha256 <추출-manifest-SHA256> --out <검사-결과.json>
python -m pytest -q scripts/qa/test_audit_lineup_csv.py
python -m ruff check scripts/qa/audit_lineup_csv.py scripts/qa/test_audit_lineup_csv.py
```

- 테스트 **4 PASS**, Ruff **PASS**. 중복·충돌, 빈 데이터/필드 오류, naive 시각, CRLF 해시 차이, 같은 kickoff의 이력 차단을 합성 자료로 확인했다.
- 실제 선수 CSV에는 아직 실행하지 않았다. 합성 검증을 실제 데이터 준비 완료로 계산하지 않는다.
- 여러 공급자 ID를 한 파일에 섞지 않는다. 파일에 없는 경기 전체 누락과 시즌 부재는 독립 fixture inventory로 추가 확인해야 한다. 0분/최대 130분 허용은 현재 exporter 계약과 맞춘 구조 검사이며 축구 경기별 사실 검증이 아니다.

## Claude에게 확인할 산출물

1. 추출 완료 여부와 CSV의 정확한 경로(서버/로컬 구분). 가능하면 QA가 접근 가능한 위치에 원본 바이트를 보존한다.
2. 실행 명령·export 코드 SHA·공급자·실행 시각·리그 ID·시즌, stderr 추출 요약/파일 SHA256. API 키·서버 비밀은 제외한다.
3. 각 시즌의 전체 fixture ID/킥오프/완료 상태 목록. 선수 상세 미수집 fixture도 남기고 요청 실패/예산 중단/공급자 미지원 사유를 별도로 제공한다.
4. 운영 readiness JSON과 생성 시각·코드 SHA. 문서에 적힌 수치만으로 대체하지 않는다.
5. 선발 발표 시각 증거가 없다면 과거 L은 대리 평가로 유지한다. 아침 M은 실제 09:00 결정 당시 저장된 snapshot으로 별도 검증한다.

## 모델 개선으로 연결할 순서

파일 확인 → hash/전체 fixture 대조 → 누락·중복 및 초기 이력 집계 → 최소 경기 수·리그·시즌 분할 확정 → 사전 등록 → baseline/candidate 동일 경기 비교. 최근 10경기 명단이 없는 팀을 숨겨 분모를 바꾸지 말고 fallback/제외를 기록한다. 정확도 개선과 비열등성은 별도 판정한다.

현재는 파일 확인이 다음 단계다. 추출이 끝났다는 증거 없이 신규 대규모 API 호출이나 모델 학습을 시작하지 않는다.
