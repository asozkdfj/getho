#!/bin/sh
# Local/dev convenience hooks. In production, run migrations as a separate,
# reviewed release step and keep both flags off.
set -eu

if [ "${RUN_MIGRATIONS_ON_STARTUP:-false}" = "true" ]; then
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
fi

if [ "${SEED_ON_STARTUP:-false}" = "true" ]; then
  echo "[entrypoint] seeding data from DATA_PROVIDER=${DATA_PROVIDER:-mock} in the background (idempotent)"
  # In the background: with every league the first run (history backfill, odds
  # pages) can take minutes, and the API must come up (and pass its health check)
  # meanwhile. Non-fatal: an upstream outage or exhausted quota must not keep the
  # API down. Concurrent pipeline runs are serialised by an advisory lock.
  (
    python -m edge_ingestion.cli seed \
      && echo "[entrypoint] seed finished" \
      || echo "[entrypoint] seed failed - continuing; run 'make seed' later"
  ) &
fi

exec "$@"
