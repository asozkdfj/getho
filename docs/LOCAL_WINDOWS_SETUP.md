# Windows 로컬 실행 환경

설정일: 2026-10-16 KST. 담당: Codex. 기준 브랜치 `codex/model-qa-contract`.

## 설치 및 실행 결과

- 기존 WSL 2 / Ubuntu-24.04를 사용했다. Docker Desktop은 설치하지 않았다.
- Ubuntu 패키지 저장소에서 Docker Engine 29.1.3, Compose 2.40.3, Buildx를 설치했다.
- Docker 컨테이너로 웹(Node 22), API(Python 3.12), PostgreSQL 16, Redis 7, Celery worker를 실행한다.
- 의존성은 저장소의 package-lock.json / uv.lock 기준으로 이미지 안에 설치했다.
- `DATA_PROVIDER=mock` 기본값으로 데모 자료를 생성했다. 유료 키 또는 실제 경기 데이터 연결은 하지 않았다.
- DB 마이그레이션·데모 수집·예측 생성 완료. 전체 스모크 테스트 통과: 이번 주 50경기, 4개 리그, 조합 계산, 오늘의 픽, 주요 웹 페이지, 잘못된 조합 요청의 422 응답.
- 브라우저에서 홈 화면과 데모 표시를 확인했다. UI 전체 품질 리뷰를 수행한 것은 아니다.

## 접속

- 웹: http://localhost:3000
- API 문서: http://localhost:18000/docs
- API 상태: http://localhost:18000/health

Windows의 8000 포트는 프로젝트 API와 다른 404 응답을 반환해 로컬 API 노출 포트를 18000으로 분리했다. 컨테이너 내부 API 포트와 웹의 내부 연결은 8000을 유지한다. `compose.local.yaml`은 공개 포트를 모두 127.0.0.1에만 바인딩한다.

## 실행 및 중지

PowerShell에서 이 checkout의 루트로 이동한다. 현재 PC 경로:

```powershell
cd C:\Users\HVS\Documents\ChatGPT\dlrjtwjrjt\getho-model-qa
.\scripts\local\stack.ps1 up
.\scripts\local\stack.ps1 status
.\scripts\local\stack.ps1 logs
.\scripts\local\stack.ps1 stop
```

`up`은 이미지 빌드 후 시작한다. `stop`은 컨테이너를 정지하고 DB 볼륨을 보존한다. 시작은 수동이며 Windows 재부팅 후 `up`을 실행한다. Compose 프로젝트 이름이 같으므로 두 checkout에서 동시에 실행하지 않는다.

WSL은 systemd 서비스만으로는 실행 상태를 유지하지 못해 최초 실행 후 종료됐다. 스크립트는 숨김 `wsl.exe ... sleep infinity` 프로세스로 미리보기 동안 WSL을 유지한다. 프로세스 ID와 시작 시각은 Git 제외 대상인 `.cache/wsl-preview-process.json`에 저장하고, `stop` 시 일치하는 프로세스만 종료한다. WSL/Docker가 켜져 있는 동안 메모리와 CPU를 사용한다.

Docker 작업은 WSL root로 실행하며 사용자에게 docker 그룹 권한을 추가하지 않았다. Windows용 `docker` 명령은 설치되지 않았으므로 이 스크립트 또는 `wsl -d Ubuntu-24.04 -u root -- docker ...`를 사용한다.

Windows checkout의 셸 스크립트에 CRLF가 있어 API entrypoint를 LF로 정규화했고, `.gitattributes`에 `*.sh text eol=lf`를 추가했다. 새 checkout에도 적용된다.

## 검증 재실행

WSL에서 프로젝트 디렉터리로 이동한 뒤:

```bash
API_URL=http://127.0.0.1:18000 bash tests/smoke/smoke.sh
```

기존 checkout의 smoke.sh가 아직 CRLF라면 새 Git checkout으로 LF 규칙을 적용하거나 LF로 정규화한 사본을 실행한다. 이번 검증은 `sed`로 CR을 제거한 스트림을 bash에 전달했다. 테스트는 로컬 데모 서비스를 대상으로 했으며 외부 실서비스에는 사용하지 않았다.

이 설정은 이 PC의 로컬 미리보기다. 외부 공개 URL이나 원격 배포는 만들지 않았다.
