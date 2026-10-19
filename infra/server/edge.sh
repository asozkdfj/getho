#!/usr/bin/env bash
# Run an `edge` command inside the running API container, e.g.
#   infra/server/edge.sh collection-quality --start 2026-10-20 --end 2026-10-26
#   infra/server/edge.sh shadow-report
source "$(dirname "$0")/common.sh"
compose exec -T api python -m edge_ingestion.cli "$@"
