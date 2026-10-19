#!/usr/bin/env bash
# Shared helpers for the server scripts (sourced, not run).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

compose() {
  docker compose -f docker-compose.yml -f docker-compose.server.yml "$@"
}

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# Value of KEY in .env (last assignment wins, quotes stripped); empty if unset.
env_value() {
  [ -f .env ] || { echo ""; return; }
  { grep -E "^$1=" .env || true; } | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

# Refuse to start with settings that are only safe on a laptop.
check_env() {
  [ -f .env ] || die ".env is missing. Create it first (docs/SERVER.md, step 5)."
  [ "$(env_value DATA_PROVIDER)" = "api_football" ] || die "DATA_PROVIDER must be api_football in .env"
  [ -n "$(env_value API_FOOTBALL_KEY)" ] || die "API_FOOTBALL_KEY is empty in .env"
  local pw
  pw="$(env_value POSTGRES_PASSWORD)"
  [ -n "$pw" ] && [ "$pw" != "edge" ] || die "Set a strong POSTGRES_PASSWORD in .env (openssl rand -hex 24)"
  [ "${#pw}" -ge 24 ] || die "POSTGRES_PASSWORD is too short (use: openssl rand -hex 24)"
  [[ "$pw" =~ ^[A-Za-z0-9]+$ ]] || die "POSTGRES_PASSWORD may only contain letters and digits (it goes into a URL)"
}

# `!reset` / `!override` in docker-compose.server.yml need Compose >= 2.24.4.
check_compose() {
  command -v docker >/dev/null || die "docker is not installed (run infra/server/setup.sh)"
  local v
  v="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
  [ -n "$v" ] || die "docker compose plugin is missing (run infra/server/setup.sh)"
  if [ "$(printf '%s\n%s\n' "2.24.4" "$v" | sort -V | head -n 1)" != "2.24.4" ]; then
    die "docker compose $v is too old (need 2.24.4+): re-run infra/server/setup.sh"
  fi
}

wait_healthy() {
  local service=$1 tries=${2:-60}
  for _ in $(seq "$tries"); do
    local id state
    id="$(compose ps -q "$service")"
    state="$( [ -n "$id" ] && docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo starting)"
    [ "$state" = "healthy" ] && return 0
    sleep 5
  done
  die "$service did not become healthy - check: infra/server/logs.sh $service"
}
