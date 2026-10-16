# 피로·휴식 후보 평가용 예측 교환 계약 v1

이 계약은 Codex가 준비한 첫 인터페이스다. Claude는 구현 전에 수용 또는 변경 필요성을 자기 작업 기록에 명시한다. 기존 운영 API나 ML 구조를 강제로 바꾸는 계약이 아니라 실험 산출물의 형식이다.

## 파일과 행

UTF-8 JSONL, 한 행은 `(fixture_id, policy_id)` 하나다. [합성 예시](prediction-contract-example.jsonl)는 형식 설명용이며 실제 경기나 성능 자료가 아니다.

| 필드 | 의미 |
| --- | --- |
| schema_version | 정수 1 |
| fixture_id / policy_id | 안정적인 경기 ID / 예측 정책 ID, 조합은 파일에서 고유 |
| decision_at / kickoff_at | 시간대 포함 ISO 시각; 경기 시작보다 먼저 결정 |
| result_available_at / outcome | 사후 채점 전용 결과 가용 시각 / 0 홈승·1 무·2 원정승; 특성 입력 금지 |
| baseline / candidate | 같은 경기·정책의 두 모델 산출물 |
| model_id | 모델 버전 또는 실험 ID; 결과 기록에서 코드 커밋과 연결 |
| training_data_available_through | 학습에 사용한 정보의 가용 시각 상한; 단순 과거 경기 시작 시각이 아님 |
| prediction_available_at | 예측 산출물을 사용할 수 있었던 시각; 결정 시각 이하 |
| probabilities | 홈/무/원정 순서의 유한한 0~1 숫자 3개, 합 1 |
| features | 후보에 추가한 변수의 name/value/missing/source/available_at |

변수 가용 시각은 예측 생성 시각 이하여야 한다. 파생 변수의 시각은 의존 입력들의 가용 시각 최댓값으로 기록한다. 결측은 `value=null`, `missing=true`, `available_at=null`로 표시하고 source에는 기대한 공급자를 기록한다. 관측되지 않은 값을 0으로 바꿔 기록하지 않는다. 보간/대치값과 규칙은 별도 메타데이터와 실험 기록에 남긴다.

과거 자료의 실제 수집 시각을 모르면 시각을 지어내지 않는다. 보수적 가정을 사용하는 연구는 별도 정책 ID와 가정 목록으로 분리하고, 실운영 재현이라고 부르지 않는다.

## 명령

저장소 루트에서 별도 패키지 설치 없이 실행한다.

```sh
python scripts/qa/check_prediction_contract.py docs/qa/prediction-contract-example.jsonl
python -m unittest discover -s scripts/qa -p test_prediction_contract.py -v
```

검사 대상: 중복 경기/정책, 시작 시점 경계, 미래 결과/학습 정보/예측/특성, 확률 벡터, 명시적 결측, 출처 누락. 타임스탬프는 원본 근거와 대조해야 한다. **이 검사는 입력의 진실성·완전한 데이터 누수 방지·표본 대표성을 증명하지 않는다.** 잘못된 학습 데이터에 올바른 시각을 붙이면 자동으로 탐지할 수 없다.

## 첫 실험에서 고정할 항목

- 변수군: 휴식 시간 차이, 최근 7/14/28일 출전량. 선수 단위가 없으면 팀 경기 수 대리 지표를 별도 이름으로 사용한다.
- 모든 대회 커버리지, 시간 창의 경계, 연장전 처리, 결측 처리, 학습/검증/평가 날짜를 실행 전에 기록한다.
- 경기 전체 manifest와 제외 사유를 별도 제출한다. 교환 파일은 두 예측이 모두 있는 표본이므로, 탈락 경기 수·결측률·리그/시즌 분포를 따로 검토한다.
- 공통 기준 모델, 정책, 동일 표본을 사용한다. 실험별 소스 해시·코드 커밋·seed·매개변수를 남긴다.
- 전체 경기 적중률, log loss, Brier, paired CI, 시즌별 결과를 보고한다. 픽 성적은 제공 비율과 분리한다.
- 주 지표·채택 기준은 후보 결과를 보기 전에 기록한다. 검증 미달 후보를 억지로 채택하지 않으며 이전 2023-26 구간은 재사용된 연구 구간으로 표시한다.
- 이 첫 계약은 결과 교환을 위한 최소 형식이다. lineup, odds, 날씨 등 추가 변수에 필요한 시점·결측 규칙은 확장 전에 기록한다.
