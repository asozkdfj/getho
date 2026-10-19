#!/usr/bin/env bash
# Recent logs: infra/server/logs.sh [service]   (api, worker, web, postgres, redis)
source "$(dirname "$0")/common.sh"
compose logs --tail=200 "$@"
