# EPL Edge Lab - developer commands. Run `make help`.
.DEFAULT_GOAL := help
SHELL := /bin/bash
export GIT_SHA ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo local)

.PHONY: help
help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup
.PHONY: install
install: ## Install Python (uv) and Node (npm) dependencies
	uv sync
	npm ci

# --------------------------------------------------------------- docker
.PHONY: up down logs ps seed check-provider
up: ## Build and start the full stack (postgres, redis, api, worker, web)
	docker compose up -d --build
	@echo "web: http://localhost:3000  api: http://localhost:8000/docs"

down: ## Stop the stack (keeps the database volume)
	docker compose down

logs: ## Tail logs of all services
	docker compose logs -f --tail=100

ps: ## Show service status
	docker compose ps

seed: ## (Re)seed data + predictions inside the running stack (idempotent)
	docker compose exec api python -m edge_ingestion.cli seed

check-provider: ## Dry-run the configured data provider (verifies API key; no DB writes)
	docker compose run --rm --no-deps -e RUN_MIGRATIONS_ON_STARTUP=false -e SEED_ON_STARTUP=false \
		api python -m edge_ingestion.cli check-provider

# ---------------------------------------------------------------- local
.PHONY: migrate seed-local api-dev web-dev
migrate: ## Apply DB migrations against DATABASE_URL
	cd apps/api && uv run alembic upgrade head

seed-local: ## Seed against DATABASE_URL without docker (idempotent)
	uv run python -m edge_ingestion.cli seed

api-dev: ## Run the API with auto-reload
	uv run uvicorn edge_api.main:app --reload --port 8000

web-dev: ## Run the web app in dev mode (API_INTERNAL_URL defaults to localhost:8000)
	npm run dev

# ------------------------------------------------------------- quality
.PHONY: lint fmt test test-py test-web typecheck contracts contracts-check smoke check
lint: ## Lint Python + web
	uv run ruff check .
	uv run ruff format --check .
	npm run lint
	npm run format:check

fmt: ## Auto-format Python + web
	uv run ruff check --fix .
	uv run ruff format .
	npm run format

typecheck: ## TypeScript type check
	npm run typecheck

test-py: ## Python tests (DB tests need TEST_DATABASE_URL / local postgres)
	uv run pytest

test-web: ## Web unit tests (Vitest)
	npm test

test: test-py test-web ## All tests

contracts: ## Regenerate packages/contracts from the FastAPI OpenAPI schema
	uv run python -m edge_api.export_openapi packages/contracts/openapi.json
	npm run contracts:generate

contracts-check: contracts ## Fail if generated contracts are out of date
	git diff --exit-code -- packages/contracts

smoke: ## Smoke-test a running stack (docker compose up first)
	./tests/smoke/smoke.sh

check: lint typecheck test ## Everything CI runs (except docker smoke)
