#!/bin/sh
# Local/dev convenience hooks. In production, run migrations as a separate,
# reviewed release step and keep both flags off.
set -eu

if [ "${RUN_MIGRATIONS_ON_STARTUP:-false}" = "true" ]; then
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
fi

if [ "${SEED_ON_STARTUP:-false}" = "true" ]; then
  echo "[entrypoint] seeding data from DATA_PROVIDER=${DATA_PROVIDER:-mock} (idempotent)"
  # Non-fatal: an upstream outage or exhausted API quota must not keep the API down.
  python -m edge_ingestion.cli seed || echo "[entrypoint] seed failed - continuing; run 'make seed' later"
fi

exec "$@"
