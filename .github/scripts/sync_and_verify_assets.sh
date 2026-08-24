#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose.custom.yaml}"
SITE_NAME="${SITE_NAME:-deeplinkerp.com}"
BACKEND_CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps -q backend)"
FRONTEND_CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps -q frontend)"
ASSETS_DIR="/home/frappe/frappe-bench/assets"
TEMP_DIR="$(mktemp -d)"

test -n "$BACKEND_CONTAINER" || { echo "backend container not found" >&2; exit 1; }
test -n "$FRONTEND_CONTAINER" || { echo "frontend container not found" >&2; exit 1; }

cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

echo "== Sync built assets to frontend =="
docker cp "${BACKEND_CONTAINER}:${ASSETS_DIR}/." "$TEMP_DIR/"
docker cp "$TEMP_DIR/." "${FRONTEND_CONTAINER}:${ASSETS_DIR}/"

echo "== Clear site cache =="
docker compose -f "$COMPOSE_FILE" exec -T backend \
    bench --site "$SITE_NAME" clear-cache
docker compose -f "$COMPOSE_FILE" exec -T backend \
    bench --site "$SITE_NAME" clear-website-cache

echo "== Verify assets.json and frontend files =="
docker compose -f "$COMPOSE_FILE" exec -T frontend \
    env ASSETS_DIR="$ASSETS_DIR" python3 - <<'PY'
import json
import os

assets_dir = os.environ["ASSETS_DIR"]
with open(os.path.join(assets_dir, "assets.json"), encoding="utf-8") as handle:
    assets = json.load(handle)

required = ("desk.bundle.css", "desk.bundle.js", "website.bundle.css")
for key in required:
    url = assets.get(key)
    if not url or not url.startswith("/assets/"):
        raise SystemExit(f"assets.json missing valid mapping: {key}={url!r}")
    path = os.path.join(assets_dir, url.removeprefix("/assets/"))
    if not os.path.isfile(path):
        raise SystemExit(f"frontend asset file missing: {key} -> {path}")
    print(f"OK {key}: {url}")
PY

echo "== Verify frontend HTTP responses =="
docker compose -f "$COMPOSE_FILE" exec -T frontend \
    env SITE_NAME="$SITE_NAME" python3 - <<'PY'
import json
import os
import subprocess
import sys

with open("/home/frappe/frappe-bench/assets/assets.json", encoding="utf-8") as handle:
    assets = json.load(handle)

for key in ("desk.bundle.css", "desk.bundle.js", "website.bundle.css"):
    url = assets[key]
    result = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "-H", f"Host: {os.environ['SITE_NAME']}", f"http://127.0.0.1:8080{url}"],
        check=False,
        stdout=subprocess.DEVNULL,
    )
    if result.returncode:
        raise SystemExit(f"frontend returned HTTP failure for {key}: {url}")
    print(f"HTTP OK {key}: {url}")
PY

echo "== Asset verification passed =="
