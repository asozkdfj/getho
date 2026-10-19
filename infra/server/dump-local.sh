#!/usr/bin/env bash
# Run on the LAPTOP (repo root) when moving to the server: stops collection,
# dumps the database to ./edge-migrate.dump and stops the local stack, so the
# laptop and the server never collect at the same time.
#   bash infra/server/dump-local.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

value() { { grep -E "^$1=" .env 2>/dev/null || true; } | tail -n 1 | cut -d= -f2- | tr -d '"'"'" ; }
user="$(value POSTGRES_USER)"; user="${user:-edge}"
db="$(value POSTGRES_DB)"; db="${db:-edge}"

echo "==> Stopping collection (worker)"
docker compose stop worker
echo "==> Dumping database '$db'"
docker compose exec -T postgres pg_dump -U "$user" -d "$db" -Fc > edge-migrate.dump.part
mv edge-migrate.dump.part edge-migrate.dump
echo "==> Stopping the local stack (data stays in its volume)"
docker compose down
ls -lh edge-migrate.dump
echo "Next: scp edge-migrate.dump <server>:~/   (docs/SERVER.md, step 6)"
