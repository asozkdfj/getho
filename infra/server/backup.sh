#!/usr/bin/env bash
# Database backup (pg_dump custom format) into ./backups, keeping the newest 14.
#   infra/server/backup.sh                 one backup now
#   infra/server/backup.sh --install-cron  plus a daily 04:30 (server time) cron job
source "$(dirname "$0")/common.sh"

if [ "${1:-}" = "--install-cron" ]; then
  line="30 4 * * * $REPO_DIR/infra/server/backup.sh >> $REPO_DIR/backups/backup.log 2>&1"
  mkdir -p backups
  ( crontab -l 2>/dev/null | grep -v 'infra/server/backup.sh' ; echo "$line" ) | crontab -
  say "Installed: $line"
fi

user="$(env_value POSTGRES_USER)"; user="${user:-edge}"
db="$(env_value POSTGRES_DB)"; db="${db:-edge}"
mkdir -p backups
out="backups/edge-$(date -u +%Y%m%d-%H%M%S).dump"
compose exec -T postgres pg_dump -U "$user" -d "$db" -Fc > "$out.part"
mv "$out.part" "$out"
say "Backup written: $out ($(du -h "$out" | cut -f1))"
ls -1t backups/edge-*.dump | tail -n +15 | xargs -r rm --
