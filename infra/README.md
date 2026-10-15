# infra

- `docker/python.Dockerfile`: one image for the API (uvicorn) and the Celery worker.
- `docker/web.Dockerfile`: Next.js standalone build.
- `docker/api-entrypoint.sh`: optional `alembic upgrade head` / seed on start (local only).

Alembic migrations live in `apps/api/migrations/` next to the ORM models (see docs/DECISIONS.md ADR-001).
Production: run migrations as an explicit release step; never enable destructive auto-migrations.
