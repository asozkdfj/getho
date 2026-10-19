#!/usr/bin/env bash
# Build and (re)start the stack on the server; also the update command.
#   infra/server/deploy.sh          rebuild and restart the current checkout
#   infra/server/deploy.sh --pull   git pull main first, then the same
source "$(dirname "$0")/common.sh"

check_compose
check_env

if [ "${1:-}" = "--pull" ]; then
  say "git pull (main)"
  git pull --ff-only origin main
fi

GIT_SHA="$(git rev-parse --short=12 HEAD)"
export GIT_SHA
say "Build and start (commit $GIT_SHA) - the first build takes several minutes"
compose up -d --build --remove-orphans

say "Waiting for the API"
wait_healthy api 90
compose ps
say "Health"
curl -fsS http://127.0.0.1:8000/health && echo
echo
echo "Open from your devices: https://<this server's name>.<your tailnet>.ts.net (docs/SERVER.md, step 7)"
