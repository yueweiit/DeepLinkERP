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
MAX_PAGES="${MAX_PAGES:-6}"
TIMEOUT="${TIMEOUT:-20}"
NEWS_TIMEOUT="${NEWS_TIMEOUT:-20}"
RETENTION_MONTHS="${RETENTION_MONTHS:-5}"
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

mkdir -p data logs

LOCK_FILE="${LOCK_FILE:-/tmp/phone_watch_daily_collect.lock}"

{
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') daily collect start ===="
  if [[ "$PHONE_WATCH_DB_BACKEND" == "postgres" && -z "${PHONE_WATCH_PG_PASSWORD:-}" ]]; then
    echo "Please set PHONE_WATCH_PG_PASSWORD before running."
    exit 1
  fi
  if command -v flock >/dev/null 2>&1; then
    flock -n "$LOCK_FILE" "$PYTHON_BIN" -m phone_watch collect \
      --max-pages "$MAX_PAGES" \
      --timeout "$TIMEOUT" \
      --retention-months "$RETENTION_MONTHS" \
      --export-out data/phone_watch.html
  else
    "$PYTHON_BIN" -m phone_watch collect \
      --max-pages "$MAX_PAGES" \
      --timeout "$TIMEOUT" \
      --retention-months "$RETENTION_MONTHS" \
      --export-out data/phone_watch.html
  fi
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') daily collect done ===="
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') daily news collect start ===="
  set +e
  "$PYTHON_BIN" -m phone_watch collect-news --timeout "$NEWS_TIMEOUT"
  NEWS_EXIT=$?
  set -e
  if [[ "$NEWS_EXIT" -ne 0 ]]; then
    echo "==== $(date '+%Y-%m-%d %H:%M:%S') daily news collect failed, main collect kept ===="
  else
    echo "==== $(date '+%Y-%m-%d %H:%M:%S') daily news collect done ===="
  fi
} >> logs/daily_collect.log 2>&1
