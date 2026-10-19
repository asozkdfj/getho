#!/usr/bin/env bash
# Load a pg_dump file into the server's EMPTY database (moving from the laptop).
# Run before the first deploy.sh; it refuses to touch a database that has tables.
#   infra/server/restore.sh ~/edge-migrate.dump
source "$(dirname "$0")/common.sh"

dump="${1:-}"
[ -n "$dump" ] && [ -f "$dump" ] || die "usage: infra/server/restore.sh <file.dump>"
check_compose
check_env
user="$(env_value POSTGRES_USER)"; user="${user:-edge}"
db="$(env_value POSTGRES_DB)"; db="${db:-edge}"

say "Starting only the database"
compose up -d postgres
wait_healthy postgres 30

tables="$(compose exec -T postgres psql -U "$user" -d "$db" -tAc \
  "select count(*) from information_schema.tables where table_schema = 'public'")"
[ "$tables" = "0" ] || die "The server database already has $tables tables - not restoring over it."

say "Restoring $dump"
compose exec -T postgres pg_restore -U "$user" -d "$db" --no-owner --role="$user" --exit-on-error < "$dump"
compose exec -T postgres psql -U "$user" -d "$db" -c \
  "select (select count(*) from predictions) as predictions, (select count(*) from odds_snapshots) as odds_snapshots, (select version_num from alembic_version) as migration"
say "Restored. Next: infra/server/deploy.sh"
