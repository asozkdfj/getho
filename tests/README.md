# tests

- Package unit tests live next to their code: `ml/tests`, `apps/api/tests`, `workers/ingestion/tests`.
- `tests/integration/`: cross-package tests (seeded DB + FastAPI TestClient, prediction snapshot
  idempotency, append-only triggers). Needs PostgreSQL (`TEST_DATABASE_URL`).
- `tests/smoke/smoke.sh`: end-to-end check of a running `docker compose` stack (`make smoke`).

Shared fixtures (Alembic schema rebuild, per-test TRUNCATE, fixed clock) are in the root `conftest.py`.
