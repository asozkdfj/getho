# Shared image for the FastAPI service and the Celery ingestion worker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN pip install --no-cache-dir uv==0.11.32

WORKDIR /app

# 1) third-party dependencies (cached layer: only invalidated by lockfile changes)
COPY pyproject.toml uv.lock ./
COPY ml/pyproject.toml ml/
COPY apps/api/pyproject.toml apps/api/
COPY workers/ingestion/pyproject.toml workers/ingestion/
RUN uv sync --frozen --no-dev --no-install-workspace

# 2) workspace packages
COPY ml ml
COPY apps/api apps/api
COPY workers/ingestion workers/ingestion
RUN uv sync --frozen --no-dev

COPY infra/docker/api-entrypoint.sh /usr/local/bin/api-entrypoint
RUN chmod +x /usr/local/bin/api-entrypoint \
    && useradd --system --uid 10001 --home /app app \
    && chown -R app /app
USER app

# Recorded on model_versions rows (pass --build-arg GIT_SHA=$(git rev-parse --short HEAD))
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

WORKDIR /app/apps/api
EXPOSE 8000
ENTRYPOINT ["api-entrypoint"]
CMD ["uvicorn", "edge_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
