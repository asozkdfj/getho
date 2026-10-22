# 항상 켜진 개인 서버 (나만 보기)

맥북을 꺼도 24시간 수집하고, 내 휴대폰과 PC에서만 화면을 여는 설정입니다.

- **구성:** 클라우드 서버 1대에 지금과 같은 docker compose를 올립니다. 접속은 [Tailscale](https://tailscale.com/)로만 합니다.
- **인터넷 공개 없음:** 인터넷에는 아무 포트도 열지 않습니다. 이 앱에는 로그인 기능이 없으므로 **절대 공개 주소로 열지 마세요.**
  `tailscale funnel`은 쓰지 않습니다.
- **DB와 Redis:** 서버 바깥으로 포트를 열지 않습니다. API와 화면은 서버 안(`127.0.0.1`)에서만 듣고, 화면은 `tailscale serve`가
  내 기기에만 HTTPS로 전달합니다(`docker-compose.server.yml`).

명령은 모두 복사해서 붙여 넣으면 됩니다. `<서버 IP>`처럼 꺾쇠로 표시한 부분만 바꾸세요. 막히면 화면에 나온 내용을 그대로 알려 주세요.

## 0. 준비물

| 준비물 | 비고 |
| --- | --- |
| AWS Lightsail 계정과 결제 카드 | 다른 업체도 Ubuntu 서버면 같은 방법으로 됩니다 |
| Tailscale 계정 | 개인 무료 플랜. 맥북과 휴대폰에 앱 설치 |
| 맥북 `.env` | 지금 쓰는 API-Football 키가 들어 있는 파일 |

**전환 시점:** 맥북과 서버가 동시에 수집하면 API 요청이 두 배로 나가고 기록도 둘로 갈라집니다. 6단계에서 맥북을 끄고 서버를
켭니다. 중단은 10~20분입니다. 오늘의 픽은 매일 오전 9시(KST)에 정해지므로 그 시각은 피하세요.

## 1. 서버 만들기 (Lightsail 웹 화면)

1. https://lightsail.aws.amazon.com 에 접속해 **인스턴스 생성**을 누릅니다.
2. 다음을 고릅니다.
   - **위치:** 서울(ap-northeast-2)
   - **플랫폼:** Linux/Unix
   - **블루프린트:** OS 전용 → **Ubuntu 24.04 LTS**
3. **SSH 키 쌍:** 기본 키를 그대로 써도 되지만, 맥북 키를 올리는 것을 권합니다.
   - 맥북 터미널에서 키를 만듭니다(이미 있으면 건너뜀). 질문에는 모두 Enter를 누르면 됩니다.
     ```bash
     ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519
     cat ~/.ssh/id_ed25519.pub
     ```
   - 출력된 한 줄 전체를 **새 키 업로드**에 붙여 넣습니다.
4. **플랜:** 메모리 **4GB**, vCPU 2개.
5. **이름:** `edge-lab`. 그리고 **인스턴스 생성**을 누릅니다.
6. 생성되면 인스턴스 → **네트워킹** 탭에서 두 가지를 합니다.
   - **고정 IP:** 생성해서 이 인스턴스에 연결합니다. 재시작해도 주소가 바뀌지 않습니다. 인스턴스에 연결된 동안은 무료입니다.
   - **방화벽(IPv4·IPv6 모두):** **SSH(22)만 남기고 HTTP(80) 규칙은 삭제**합니다.

## 2. 접속하기

맥북 터미널에서 접속합니다. Lightsail Ubuntu의 기본 사용자는 `ubuntu`입니다.
```bash
ssh ubuntu@<서버 IP>
```
처음에 `Are you sure you want to continue connecting` 질문이 나오면 `yes`를 입력합니다. 이제부터 3~8단계는 **서버에서** 실행합니다.

## 3. 저장소 받기

저장소가 **공개**라면 `git clone https://github.com/asozkdfj/getho.git`만 실행하고 넘어가면 됩니다.

**비공개**라면 서버 전용 읽기 키(Deploy key)를 만듭니다.
```bash
ssh-keygen -t ed25519 -f ~/.ssh/getho_deploy -N "" -C edge-lab-server
cat ~/.ssh/getho_deploy.pub
```
1. 출력된 한 줄을 GitHub → 저장소 → **Settings → Deploy keys → Add deploy key**에 붙여 넣습니다.
2. **Allow write access는 체크하지 않습니다.**

그다음 그 키로 저장소를 받습니다.
```bash
printf 'Host github.com\n  IdentityFile ~/.ssh/getho_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
ssh -o StrictHostKeyChecking=accept-new -T git@github.com   # "successfully authenticated" 가 나오면 성공
git clone git@github.com:asozkdfj/getho.git
```

## 4. 서버 준비 (한 번만)

```bash
cd ~/getho
bash infra/server/setup.sh
exit
```
- `setup.sh`가 하는 일: 시스템 업데이트, Docker와 Tailscale 설치, 2GB 스왑, SSH만 허용하는 방화벽, 자동 보안 업데이트.
- 끝나면 `exit`로 나갔다가 `ssh ubuntu@<서버 IP>`로 **다시 접속**합니다(Docker 권한 적용).

다시 접속한 뒤 Tailscale에 연결합니다.
```bash
sudo tailscale up
```
1. 출력된 주소(`https://login.tailscale.com/...`)를 맥북 브라우저에서 열고, 휴대폰과 **같은 계정**으로 로그인합니다.
2. Tailscale 관리 화면(https://login.tailscale.com/admin)에서 두 가지를 설정합니다.
   - **DNS** 탭: **MagicDNS**와 **HTTPS Certificates**를 켭니다.
   - **Machines** 탭: `edge-lab` 옆 메뉴에서 **Disable key expiry**를 누릅니다(몇 달 뒤 연결이 끊기지 않게).

## 5. 설정 파일(.env) 만들기

**맥북에서** 지금 쓰는 `.env`를 서버로 복사합니다(맥북의 저장소 폴더에서 실행).
```bash
scp .env ubuntu@<서버 IP>:~/getho/.env
```

**서버에서** DB 비밀번호를 새로 만들어 넣고 확인합니다.
```bash
cd ~/getho
grep -q '^POSTGRES_PASSWORD=' .env || echo 'POSTGRES_PASSWORD=' >> .env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
chmod 600 .env
grep -E '^(DATA_PROVIDER|POSTGRES_PASSWORD)=' .env
```
- `DATA_PROVIDER=api_football`이어야 합니다.
- 비밀번호는 긴 영문·숫자 한 줄이면 됩니다.
- 키 값은 화면에 출력하지 마세요(채팅에도 붙여 넣지 않습니다).
- 비밀번호가 짧거나 `edge`이면 다음 단계의 스크립트가 시작을 거부합니다.

## 6. 맥북 데이터 옮기기 (전환)

지금까지 맥북에 쌓인 예측, 배당 기록, 병행 기록을 그대로 옮깁니다. 모두 다시 만들 수 없는 누적 기록입니다.

**맥북에서** (저장소 폴더) 실행합니다. 수집을 멈추고, DB를 파일로 내보내고, 맥북 스택을 끕니다. 맥북 데이터는 지워지지 않습니다.
```bash
git pull origin main
bash infra/server/dump-local.sh
scp edge-migrate.dump ubuntu@<서버 IP>:~/
```

**서버에서** 실행합니다.
```bash
cd ~/getho
infra/server/restore.sh ~/edge-migrate.dump
```
- 예측 수, 배당 기록 수, 마이그레이션 번호가 출력되면 성공입니다.
- 이미 데이터가 있는 DB에는 복원하지 않고 멈춥니다.
- 이후 맥북에서는 실데이터로 `make up`을 하지 마세요. 서버와 동시에 수집하게 됩니다.

## 7. 실행하고 휴대폰으로 열기

**서버에서** 실행합니다.
```bash
cd ~/getho
infra/server/deploy.sh
sudo tailscale serve --bg 3000
tailscale serve status
```
- 첫 빌드는 5~10분 걸립니다. 마지막에 `/health` 결과(JSON)가 나오면 성공입니다.
- `tailscale serve status`에 나온 `https://edge-lab.<…>.ts.net` 주소를 휴대폰에서 엽니다. 휴대폰 Tailscale 앱이 **연결됨** 상태여야
  합니다. 홈 화면에 추가해 두면 앱처럼 쓸 수 있습니다.
- Tailscale에 연결되지 않은 기기에서는 이 주소가 열리지 않습니다. 정상입니다.

## 8. 매일 자동 백업

```bash
cd ~/getho
infra/server/backup.sh --install-cron
```
- 매일 04:30(서버 시각, UTC)에 `~/getho/backups/`에 DB를 저장하고, 최근 14개만 남깁니다.
- 가끔 맥북으로도 받아 두세요(맥북의 저장소 폴더에서 실행). `server-backups/`와 `*.dump`는 git에 올라가지 않습니다.
  ```bash
  mkdir -p server-backups && scp 'ubuntu@<서버 IP>:~/getho/backups/*.dump' server-backups/
  ```

## 9. 수집 실패 알림 (텔레그램)

수집이 연달아 실패하거나, 8시간 넘게 성공한 수집이 없거나, 09:00 픽 결정이 90분 지나도 없으면 휴대폰으로 알려 줍니다.
고쳐지면 "해결" 메시지가 오고, 계속 문제면 12시간마다 다시 알려 줍니다. API 컨테이너나 DB가 죽어서 점검 자체를 못 하면
서버가 직접 한 번 알려 줍니다(12시간에 한 번).

1. **봇 만들기 (휴대폰 텔레그램):** `@BotFather`에게 `/newbot` → 이름 입력 → **토큰**을 받습니다.
   토큰은 비밀번호와 같습니다. **채팅(Claude 포함)에 붙여 넣지 말고** 서버 `.env`에만 넣습니다.
2. 만든 봇과 대화방을 열고 아무 메시지나 한 번 보냅니다(봇은 먼저 말을 걸 수 없습니다).
3. **chat id 찾기 (서버에서):** 토큰은 화면에 남지 않게 `read -s`로 입력합니다.
   ```bash
   read -rs TOKEN && curl -s "https://api.telegram.org/bot$TOKEN/getUpdates" | grep -o '"chat":{"id":-\?[0-9]*' | head -1; unset TOKEN
   ```
   나온 숫자가 chat id입니다.
4. **`.env`에 추가:** `nano .env`로 열어 두 줄을 넣고 저장합니다.
   ```
   TELEGRAM_BOT_TOKEN=<봇 토큰>
   TELEGRAM_CHAT_ID=<chat id>
   ```
5. **반영하고 시험·등록:**
   ```bash
   infra/server/deploy.sh
   infra/server/alerts.sh --test
   infra/server/alerts.sh --install-cron
   ```
   `--test` 뒤에 휴대폰에 "알림 테스트 메시지"가 오면 됩니다. 이후 10분마다 점검하고 기록은 `backups/alerts.log`에 남습니다.
- 서버 전체가 꺼지면(전원·네트워크) 알림을 보낼 곳이 없어 알 수 없습니다. 이 경우는 `/status/data` 배지로 확인합니다.

## 평소에 쓰는 명령 (서버의 `~/getho`에서)

| 하고 싶은 것 | 명령 |
| --- | --- |
| 새 버전으로 업데이트(PR 병합 후) | `infra/server/deploy.sh --pull` |
| 상태 보기 | `infra/server/deploy.sh`의 마지막 출력, 또는 `curl -s http://127.0.0.1:8000/health` |
| 로그 보기 | `infra/server/logs.sh worker` (api, web, postgres도 가능) |
| 수집 품질 리포트 | `infra/server/edge.sh collection-quality --start 2026-10-20 --end 2026-10-26` |
| 병행 기록 채점(12월) | `infra/server/edge.sh shadow-report` |
| 지금 백업 | `infra/server/backup.sh` |
| 알림 점검 지금 실행 / 시험 메시지 | `infra/server/alerts.sh` / `infra/server/alerts.sh --test` |
| 디스크 확인 | `df -h /` |

## 문제 해결

- **`.env`에 대해 ERROR가 나올 때:** 메시지가 알려 주는 값을 5단계처럼 고칩니다.
- **화면이 안 열릴 때:**
  1. 휴대폰 Tailscale이 켜져 있는지 확인합니다.
  2. 서버에서 `tailscale serve status`를 실행해 3000번 포트가 연결돼 있는지 봅니다.
  3. `infra/server/logs.sh web`으로 화면 서버 로그를 봅니다.
- **수집이 안 될 때:** `infra/server/logs.sh worker`로 로그를 보고, API 요청 한도 메시지가 있는지 확인합니다.
- **서버 재시작 후:** 컨테이너는 자동으로 다시 뜹니다(`restart: unless-stopped`). Tailscale serve 설정도 유지됩니다.

## 비용과 정리

- **비용:** Lightsail은 인스턴스가 **존재하는 동안** 요금이 나갑니다. 중지해도 요금이 나갑니다.
- **그만 쓸 때:** 백업을 맥북으로 받은 뒤 인스턴스를 삭제하고, 고정 IP도 해제합니다(연결되지 않은 고정 IP는 과금됩니다).
