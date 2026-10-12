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

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
PHONE_WATCH_DB_BACKEND="${PHONE_WATCH_DB_BACKEND:-postgres}"
PHONE_WATCH_PG_DRIVER="${PHONE_WATCH_PG_DRIVER:-pg8000}"
PHONE_WATCH_PG_HOST="${PHONE_WATCH_PG_HOST:-127.0.0.1}"
PHONE_WATCH_PG_DATABASE="${PHONE_WATCH_PG_DATABASE:-phone_scraper}"
PHONE_WATCH_PG_USER="${PHONE_WATCH_PG_USER:-postgres}"
PHONE_WATCH_PG_PORT="${PHONE_WATCH_PG_PORT:-5432}"
PHONE_WATCH_PG_OPTIONS="${PHONE_WATCH_PG_OPTIONS:--c client_encoding=utf8}"
PHONE_WATCH_PG_CONNECT_TIMEOUT="${PHONE_WATCH_PG_CONNECT_TIMEOUT:-10}"
export PHONE_WATCH_DB_BACKEND PHONE_WATCH_PG_DRIVER PHONE_WATCH_PG_HOST PHONE_WATCH_PG_DATABASE
export PHONE_WATCH_PG_USER PHONE_WATCH_PG_PORT PHONE_WATCH_PG_OPTIONS PHONE_WATCH_PG_CONNECT_TIMEOUT

if [[ "$PHONE_WATCH_DB_BACKEND" == "postgres" && -z "${PHONE_WATCH_PG_PASSWORD:-}" ]]; then
  echo "Please set PHONE_WATCH_PG_PASSWORD before running." >&2
  exit 1
fi

mkdir -p data logs
exec "$PYTHON_BIN" -m phone_watch serve --host "$HOST" --port "$PORT"
