#!/usr/bin/env bash
# Start the full stack in a codespace (also usable by hand: bash .devcontainer/start.sh).
#
# Secrets stay in the environment: docker compose gives shell variables
# precedence over .env, so API_FOOTBALL_KEY / DATA_PROVIDER from Codespaces
# secrets override the template's empty/mock values without touching disk.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || bash .devcontainer/setup-env.sh

if [[ -n "${API_FOOTBALL_KEY:-}" && -z "${DATA_PROVIDER:-}" ]]; then
  export DATA_PROVIDER=api_football
fi
echo "data provider: ${DATA_PROVIDER:-mock (from .env)}"

# docker-in-docker may need a moment after the container starts
for _ in $(seq 1 30); do
  docker info >/dev/null 2>&1 && break
  sleep 2
done

GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo local)" \
  docker compose up -d --build

echo "stack is starting: open the forwarded port 3000 (PORTS tab)."
echo "first build takes a few minutes; logs: docker compose logs -f api web"
