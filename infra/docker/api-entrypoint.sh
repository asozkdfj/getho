#!/bin/sh
# Local/dev convenience hooks. In production, run migrations as a separate,
# reviewed release step and keep both flags off.
set -eu

if [ "${RUN_MIGRATIONS_ON_STARTUP:-false}" = "true" ]; then
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
fi

if [ "${SEED_ON_STARTUP:-false}" = "true" ]; then
  echo "[entrypoint] seeding mock data (idempotent)"
  python -m edge_ingestion.cli seed
fi

exec "$@"
