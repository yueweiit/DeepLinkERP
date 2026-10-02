#!/usr/bin/env bash
set -euo pipefail

mode="${1:?prepare, finish, recover-maintenance, rollback-safe, rollback or rollback-code is required}"
compose_root="${2:-/home/yuewei/ERPNext-Docker/frappe_docker}"
site_name="${3:-deeplinkerp.com}"
release_id="${4:?release id is required}"
[[ "$release_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid release id" >&2; exit 2; }
[[ "$site_name" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "Invalid site name" >&2; exit 2; }

compose_file="$compose_root/compose.custom.yaml"
backup_image="deeplinkerp-custom:pre-material-ai-release-$release_id"
backup_archive="$compose_root/backups/material-ai-release-$release_id.tar.gz"
release_marker_backup="$compose_root/backups/workbench-release-$release_id.json"
release_state_file="$compose_root/backups/release-state-$release_id.json"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
asset_sync_script="${ASSET_SYNC_SCRIPT:-}"
if [ -z "$asset_sync_script" ] && [ -f "$script_dir/sync_and_verify_assets.sh" ]; then
  asset_sync_script="$script_dir/sync_and_verify_assets.sh"
fi
base_image_script="${BASE_IMAGE_SCRIPT:-}"
if [ -z "$base_image_script" ] && [ -f "$script_dir/resolve_base_image.sh" ]; then
  base_image_script="$script_dir/resolve_base_image.sh"
fi
if [ -z "$base_image_script" ]; then
  echo "Cannot locate resolve_base_image.sh (set BASE_IMAGE_SCRIPT)" >&2
  exit 2
fi
# shellcheck source=resolve_base_image.sh
. "$base_image_script"
base_image="$(resolve_base_image "$compose_file")"

cd "$compose_root"

sync_and_verify_assets_only() {
  if [ -n "$asset_sync_script" ]; then
    test -f "$asset_sync_script"
    COMPOSE_FILE="$compose_file" SITE_NAME="$site_name" VERIFY_APP_RELEASE=0 bash "$asset_sync_script"
  fi
}

prepare_release() {
  mkdir -p "$compose_root/backups"
  rm -f "$release_state_file"
  backend_id=$(docker compose -f "$compose_file" ps -q backend)
  test -n "$backend_id"
  marker_config=$(mktemp)
  docker cp "$backend_id:/home/frappe/frappe-bench/sites/$site_name/site_config.json" "$marker_config"
  python3 - "$marker_config" "$release_marker_backup" <<'PY'
import json
import sys

source, target = sys.argv[1:]
with open(source, encoding="utf-8") as handle:
    config = json.load(handle)
key = "overseas_costing_release_id"
with open(target, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "present": key in config,
            "value": config.get(key) or "",
            "maintenance_mode": {
                "present": "maintenance_mode" in config,
                "value": config.get("maintenance_mode", 0),
            },
        },
        handle,
    )
PY
  rm -f "$marker_config"
  test -s "$release_marker_backup"
  maintenance_armed=0
  restore_on_prepare_error() {
    status=$?
    if [ "$maintenance_armed" -eq 1 ]; then
      restore_maintenance_mode || true
    fi
    exit "$status"
  }
  trap restore_on_prepare_error ERR
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" set-maintenance-mode on
  maintenance_armed=1
  for attempt in $(seq 1 10); do
    if docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
      bench --site "$site_name" ready-for-migration; then
      break
    fi
    if [ "$attempt" -eq 10 ]; then
      echo "Site still has pending background jobs after entering maintenance mode" >&2
      return 1
    fi
    sleep 3
  done
  docker image inspect "$base_image" >/dev/null
  docker image tag "$base_image" "$backup_image"
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" backup --with-files
  docker compose -f "$compose_file" exec -T backend sh -lc '
    set -eu
    cd "/home/frappe/frappe-bench/sites/'"$site_name"'/private/backups"
    database=$(ls -1t *-database.sql.gz | head -1)
    set -- "$database"
    public=$(ls -1t *-files.tar 2>/dev/null | head -1 || true)
    private=$(ls -1t *-private-files.tar 2>/dev/null | head -1 || true)
    config=$(ls -1t *-site_config_backup.json 2>/dev/null | head -1 || true)
    [ -z "$public" ] || set -- "$@" "$public"
    [ -z "$private" ] || set -- "$@" "$private"
    [ -z "$config" ] || set -- "$@" "$config"
    tar -czf - "$@"
  ' > "$backup_archive"
  test -s "$backup_archive"
  trap - ERR
}

restore_maintenance_mode() {
  test -s "$release_marker_backup"
  previous_state=$(python3 - "$release_marker_backup" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    marker = json.load(handle)
value = (marker.get("maintenance_mode") or {}).get("value", 0)
print("on" if str(value).strip().lower() in {"1", "true", "yes", "on"} else "off")
PY
  )
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" clear-cache
  # Restoring the site's previous write state is intentionally the final
  # fallible command.  Nothing may fail after writes are admitted again.
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" set-maintenance-mode "$previous_state"
}

finish_release() {
  mark_database_committed
  restore_maintenance_mode
}

mark_database_committed() {
  python3 - "$release_state_file" <<'PY'
import json
import os
import sys

target = os.path.abspath(sys.argv[1])
temporary = f"{target}.tmp-{os.getpid()}"
with open(temporary, "w", encoding="utf-8") as handle:
    json.dump({"state": "database_committed"}, handle)
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, target)
directory = os.open(os.path.dirname(target), os.O_RDONLY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}

database_is_committed() {
  test -s "$release_state_file" || return 1
  python3 - "$release_state_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
raise SystemExit(0 if state.get("state") == "database_committed" else 1)
PY
}

current_maintenance_state() {
  local backend_id current_config status
  backend_id=$(docker compose -f "$compose_file" ps -q backend)
  test -n "$backend_id"
  current_config=$(mktemp)
  if ! docker cp "$backend_id:/home/frappe/frappe-bench/sites/$site_name/site_config.json" "$current_config"; then
    rm -f "$current_config"
    return 1
  fi
  set +e
  python3 - "$current_config" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle).get("maintenance_mode", 0)
print("on" if str(value).strip().lower() in {"1", "true", "yes", "on"} else "off")
PY
  status=$?
  set -e
  rm -f "$current_config"
  return "$status"
}

recover_maintenance_after_rollback() {
  state=$(current_maintenance_state) || {
    echo "Cannot read the current maintenance state; refusing recovery" >&2
    return 1
  }
  if [ "$state" != "on" ]; then
    echo "Site is not in maintenance mode; no recovery is required"
    return 0
  fi
  if database_is_committed; then
    echo "Release database is committed; refusing failed-release recovery" >&2
    return 1
  fi
  restore_maintenance_mode
}

rollback_release() {
  docker image inspect "$backup_image" >/dev/null
  test -s "$backup_archive"
  restore_dir=$(mktemp -d)
  trap 'rm -rf "$restore_dir"' EXIT
  tar -xzf "$backup_archive" -C "$restore_dir"
  database=$(find "$restore_dir" -maxdepth 1 -name '*-database.sql.gz' -print -quit)
  public=$(find "$restore_dir" -maxdepth 1 -name '*-files.tar' ! -name '*-private-files.tar' -print -quit)
  private=$(find "$restore_dir" -maxdepth 1 -name '*-private-files.tar' -print -quit)
  config=$(find "$restore_dir" -maxdepth 1 -name '*-site_config_backup.json' -print -quit)
  test -n "$database"

  docker compose -f "$compose_file" stop frontend websocket queue-short queue-long scheduler >/dev/null
  docker image tag "$backup_image" "$base_image"
  docker compose -f "$compose_file" up -d --no-deps --force-recreate backend
  backend_id=$(docker compose -f "$compose_file" ps -q backend)
  test -n "$backend_id"
  database_id=$(docker compose -f "$compose_file" ps -q db)
  test -n "$database_id"
  database_root_password=$(
    docker inspect "$database_id" --format '{{json .Config.Env}}' |
      python3 -c 'import json, sys; values = json.load(sys.stdin); print(next((value.split("=", 1)[1] for value in values if value.startswith("MYSQL_ROOT_PASSWORD=")), ""))'
  )
  test -n "$database_root_password"
  remote_dir="/tmp/material-ai-rollback-$release_id"
  docker exec "$backend_id" mkdir -p "$remote_dir"
  docker cp "$restore_dir/." "$backend_id:$remote_dir/"

  restore_args=(bench --site "$site_name" restore "$remote_dir/$(basename "$database")" --force \
    --db-root-username root --db-root-password "$database_root_password")
  [ -z "$public" ] || restore_args+=(--with-public-files "$remote_dir/$(basename "$public")")
  [ -z "$private" ] || restore_args+=(--with-private-files "$remote_dir/$(basename "$private")")
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend "${restore_args[@]}"
  unset database_root_password
  if [ -n "$config" ]; then
    docker compose -f "$compose_file" exec -T backend sh -lc \
      "cp '$remote_dir/$(basename "$config")' '/home/frappe/frappe-bench/sites/$site_name/site_config.json' && chown frappe:frappe '/home/frappe/frappe-bench/sites/$site_name/site_config.json' && chmod 640 '/home/frappe/frappe-bench/sites/$site_name/site_config.json'"
  fi
  docker exec "$backend_id" rm -rf "$remote_dir"
  docker compose -f "$compose_file" up -d --force-recreate \
    backend websocket queue-short queue-long scheduler frontend
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" clear-cache
  asset_status=0
  sync_and_verify_assets_only || asset_status=$?
  restore_maintenance_mode
  return "$asset_status"
}

rollback_safe_release() {
  if database_is_committed; then
    echo "Release database is committed; retry maintenance restoration without database rollback"
    restore_maintenance_mode
    return
  fi

  state=$(current_maintenance_state) || {
    echo "Cannot prove the site is still in maintenance mode; refusing database rollback" >&2
    return 1
  }
  if [ "$state" != "on" ]; then
    echo "Site accepts writes and release is not committed; refusing database rollback" >&2
    return 1
  fi
  rollback_release
}

rollback_code_release() {
  # Additive releases retain the current database, files and site configuration.
  # The original rollback mode remains available for deliberate full recovery.
  docker image inspect "$backup_image" >/dev/null
  test -s "$release_marker_backup"
  docker compose -f "$compose_file" stop frontend websocket queue-short queue-long scheduler >/dev/null
  docker image tag "$backup_image" "$base_image"
  docker compose -f "$compose_file" up -d --no-deps --force-recreate backend

  # Run UI restoration from the restored image, never the failed release's code.
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench/sites backend \
    env SITE_NAME="$site_name" /home/frappe/frappe-bench/env/bin/python - <<'PY'
import os

import frappe
from overseas_costing import install

frappe.init(site=os.environ["SITE_NAME"])
frappe.connect()
frappe.set_user("Administrator")
try:
    result = install.ensure_workspace_sidebar()
    if not result.get("ok"):
        raise RuntimeError(result.get("message") or "Cannot restore the previous workspace sidebar")
    # Restore only workspace navigation; ensure_workspace also adjusts ERP defaults.
    for candidate in install.WORKSPACE_NAME_CANDIDATES:
        name = (frappe.db.exists("Workspace", candidate)
                or frappe.db.exists("Workspace", {"label": candidate})
                or frappe.db.exists("Workspace", {"title": candidate}))
        if name:
            workspace = frappe.get_doc("Workspace", name)
            install._set_workspace_content(workspace)
            workspace.save(ignore_permissions=True)
            break
    # Desk caches native page assets by Page.modified, independently of clear-cache.
    frappe.db.set_value("Page", install.WORKBENCH_PAGE, "modified", frappe.utils.now_datetime())
    frappe.db.commit()
finally:
    frappe.destroy()
PY

  docker compose -f "$compose_file" up -d --force-recreate \
    backend websocket queue-short queue-long scheduler frontend
  backend_id=$(docker compose -f "$compose_file" ps -q backend)
  frontend_id=$(docker compose -f "$compose_file" ps -q frontend)
  test -n "$backend_id" && test -n "$frontend_id"
  rollback_assets_dir=$(mktemp -d)
  trap 'rm -rf "$rollback_assets_dir"' EXIT
  docker cp "$backend_id:/home/frappe/frappe-bench/assets/." "$rollback_assets_dir/"
  test -s "$rollback_assets_dir/assets.json"
  docker cp "$rollback_assets_dir/." "$frontend_id:/home/frappe/frappe-bench/assets/"
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" clear-cache
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" clear-website-cache
  asset_status=0
  sync_and_verify_assets_only || asset_status=$?
  previous_release_id=$(python3 - "$release_marker_backup" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    marker = json.load(handle)
print(str(marker.get("value") or ""))
PY
  )
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" set-config overseas_costing_release_id "$previous_release_id"
  restore_maintenance_mode
  return "$asset_status"
}

case "$mode" in
  prepare) prepare_release ;;
  finish) finish_release ;;
  recover-maintenance) recover_maintenance_after_rollback ;;
  rollback-safe) rollback_safe_release ;;
  rollback) rollback_release ;;
  rollback-code) rollback_code_release ;;
  *) echo "Unknown mode: $mode" >&2; exit 2 ;;
esac
