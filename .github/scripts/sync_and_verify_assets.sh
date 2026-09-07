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

echo "== Verify overseas costing application release =="
docker compose -f "$COMPOSE_FILE" exec -T backend \
    env FRAPPE_STREAM_LOGGING=1 SITE_NAME="$SITE_NAME" \
    /home/frappe/frappe-bench/env/bin/python - <<'PY'
import os
import uuid
from io import BytesIO
from pathlib import Path

import frappe
from minio.error import S3Error

from overseas_costing.api import packing_api
from overseas_costing.api import workbench
from overseas_costing.integrations.dingtalk_packing_source import get_packing_runtime_clients

if not hasattr(workbench, "get_batch_dingtalk_approval_detail"):
    raise SystemExit("backend is missing get_batch_dingtalk_approval_detail")
if not hasattr(packing_api, "preview_freight_comparison"):
    raise SystemExit("backend is missing packing_api.preview_freight_comparison")

page_script = Path(
    "/home/frappe/frappe-bench/apps/overseas_costing/overseas_costing/"
    "overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js"
)
if not page_script.is_file():
    raise SystemExit(f"workbench page script is missing: {page_script}")
if "renderDingtalkApprovalTab" not in page_script.read_text(encoding="utf-8"):
    raise SystemExit("workbench page script is missing renderDingtalkApprovalTab")
page_source = page_script.read_text(encoding="utf-8")
for marker in ("openPackingFlowDialog", "独立试算，不修改正式费用"):
    if marker not in page_source:
        raise SystemExit(f"workbench page script is missing {marker}")

frappe.init(site=os.environ["SITE_NAME"], sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
try:
    for doctype in ("Overseas Packing Snapshot", "Overseas Freight Comparison"):
        if not frappe.db.exists("DocType", doctype):
            raise SystemExit(f"missing DocType after migrate: {doctype}")

    clients = get_packing_runtime_clients()
    views = (
        "packing_workbooks_v1",
        "packing_sheet_index_v1",
        "packing_sheet_snapshots_v1",
        "packing_refresh_status_v1",
    )
    with clients.catalog._connection() as connection:
        with connection.cursor() as cursor:
            for view in views:
                cursor.execute(f"SELECT 1 FROM costing_read.{view} LIMIT 1")
                cursor.fetchone()
            cursor.execute(
                """
                SELECT p.proname,
                       has_function_privilege('costing_job_submitter', p.oid, 'EXECUTE') AS submitter_can_execute,
                       has_function_privilege('costing_reader', p.oid, 'EXECUTE') AS reader_can_execute,
                       EXISTS (
                           SELECT 1
                             FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
                            WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                       ) AS public_can_execute
                  FROM pg_proc p
                  JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'costing_read'
                   AND p.proname IN (
                       'request_packing_workbook_index_refresh',
                       'request_packing_sheet_refresh'
                   )
                """
            )
            grants = cursor.fetchall()
            if len(grants) != 2:
                raise SystemExit("packing refresh functions are missing")
            for grant in grants:
                values = dict(grant) if hasattr(grant, "keys") else {
                    "submitter_can_execute": grant[1],
                    "reader_can_execute": grant[2],
                    "public_can_execute": grant[3],
                }
                if not values["submitter_can_execute"] or values["reader_can_execute"] or values["public_can_execute"]:
                    raise SystemExit("packing refresh function grants are not least privilege")
            for table in (
                "allowed_packing_workbook",
                "packing_sheet_index",
                "packing_sheet_snapshot",
                "packing_refresh_request",
            ):
                cursor.execute(
                    "SELECT has_table_privilege('costing_job_submitter', %s, 'SELECT,INSERT,UPDATE,DELETE')",
                    (f"costing_read.{table}",),
                )
                privilege_row = cursor.fetchone()
                has_privilege = next(iter(privilege_row.values())) if hasattr(privilege_row, "values") else privilege_row[0]
                if has_privilege:
                    raise SystemExit(f"costing_job_submitter has direct table privilege: {table}")
                cursor.execute(
                    "SELECT has_table_privilege('costing_reader', %s, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
                    (f"costing_read.{table}",),
                )
                reader_row = cursor.fetchone()
                reader_can_write = next(iter(reader_row.values())) if hasattr(reader_row, "values") else reader_row[0]
                if reader_can_write:
                    raise SystemExit(f"costing_reader has write privilege: {table}")

    # 先验证可读，再用唯一零字节 canary 验证读账号确实被拒绝写入。
    next(iter(clients.archive.client.list_objects(clients.archive.bucket, recursive=False)), None)
    canary_key = f"permission-smoke/{uuid.uuid4().hex}.canary"
    try:
        clients.archive.client.put_object(
            clients.archive.bucket,
            canary_key,
            BytesIO(b""),
            0,
            content_type="application/octet-stream",
        )
    except S3Error as error:
        if error.code not in {"AccessDenied", "MethodNotAllowed"}:
            raise SystemExit(f"unexpected MinIO write check failure: {error.code}") from error
    else:
        try:
            clients.archive.client.remove_object(clients.archive.bucket, canary_key)
        finally:
            raise SystemExit("MinIO reader unexpectedly accepted a write")
finally:
    frappe.destroy()

print("OK approval, packing API, DocTypes, PostgreSQL read-only grants/views and MinIO read-only enforcement")
PY

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
