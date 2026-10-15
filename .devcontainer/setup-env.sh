#!/usr/bin/env bash
# Create .env from the template once (it is gitignored and holds no secrets).
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "created .env from .env.example"
fi
