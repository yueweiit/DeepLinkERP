#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

HOST="${HEALTH_HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

curl -fsS "http://${HOST}:${PORT}/api/summary"
echo

