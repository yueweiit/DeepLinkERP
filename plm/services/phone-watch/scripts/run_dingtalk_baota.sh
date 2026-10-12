#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env.baota}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
elif [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
DINGTALK_HOST="${DINGTALK_HOST:-0.0.0.0}"
DINGTALK_PORT="${DINGTALK_PORT:-5011}"

mkdir -p logs
exec "$PYTHON_BIN" -m phone_watch serve-dingtalk --host "$DINGTALK_HOST" --port "$DINGTALK_PORT"
