#!/usr/bin/env bash
# Collection alerts to Telegram (docs/SERVER.md, "알림").
#   infra/server/alerts.sh                 check once now
#   infra/server/alerts.sh --test          send one test message
#   infra/server/alerts.sh --install-cron  plus a check every 10 minutes
# The check runs `edge check-alerts` in the API container. If that cannot run at
# all (container or database down), a message is sent from the host instead, at
# most once every 12 hours until a check succeeds again.
source "$(dirname "$0")/common.sh"

if [ "${1:-}" = "--install-cron" ]; then
  line="*/10 * * * * $REPO_DIR/infra/server/alerts.sh >> $REPO_DIR/backups/alerts.log 2>&1"
  mkdir -p backups
  # no crontab yet (crontab -l fails) or nothing left after grep -v must not stop the script
  ( { crontab -l 2>/dev/null || true; } | { grep -v 'infra/server/alerts.sh' || true; }
    echo "$line" ) | crontab -
  say "Installed: $line"
  shift
fi

args=(check-alerts)
[ "${1:-}" = "--test" ] && args+=(--test)

marker="$REPO_DIR/backups/.alerts-check-failed"
if compose exec -T api python -m edge_ingestion.cli "${args[@]}"; then
  rm -f "$marker"
  exit 0
fi

token="$(env_value TELEGRAM_BOT_TOKEN)"
chat="$(env_value TELEGRAM_CHAT_ID)"
if [ -n "$token" ] && [ -n "$chat" ] && [ -z "$(find "$marker" -mmin -720 2>/dev/null)" ]; then
  mkdir -p "$(dirname "$marker")"
  text="[EPL Edge Lab] ⚠️ 알림 점검을 실행하지 못했어요 ($(date -u '+%m-%d %H:%M') UTC). api 컨테이너나 DB를 확인하세요: infra/server/logs.sh api"
  # the token goes through stdin, not the command line (visible in ps)
  if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" |
    curl -fsS -m 10 -K - --data-urlencode "chat_id=$chat" --data-urlencode "text=$text" >/dev/null; then
    touch "$marker"
  fi
fi
die "check-alerts could not run (see above)"
