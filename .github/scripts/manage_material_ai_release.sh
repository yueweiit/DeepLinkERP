#!/usr/bin/env bash
set -euo pipefail

mode="${1:?prepare or rollback is required}"
compose_root="${2:-/home/yuewei/ERPNext-Docker/frappe_docker}"
site_name="${3:-deeplinkerp.com}"
release_id="${4:?release id is required}"
[[ "$release_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid release id" >&2; exit 2; }
[[ "$site_name" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "Invalid site name" >&2; exit 2; }

compose_file="$compose_root/compose.custom.yaml"
base_image="deeplinkerp-custom:v16.23.0-latest"
backup_image="deeplinkerp-custom:pre-material-ai-release-$release_id"
backup_archive="$compose_root/backups/material-ai-release-$release_id.tar.gz"

cd "$compose_root"

prepare_release() {
  mkdir -p "$compose_root/backups"
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
  remote_dir="/tmp/material-ai-rollback-$release_id"
  docker exec "$backend_id" mkdir -p "$remote_dir"
  docker cp "$restore_dir/." "$backend_id:$remote_dir/"

  restore_args=(bench --site "$site_name" restore "$remote_dir/$(basename "$database")" --force)
  [ -z "$public" ] || restore_args+=(--with-public-files "$remote_dir/$(basename "$public")")
  [ -z "$private" ] || restore_args+=(--with-private-files "$remote_dir/$(basename "$private")")
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend "${restore_args[@]}"
  if [ -n "$config" ]; then
    docker compose -f "$compose_file" exec -T backend sh -lc \
      "cp '$remote_dir/$(basename "$config")' '/home/frappe/frappe-bench/sites/$site_name/site_config.json' && chown frappe:frappe '/home/frappe/frappe-bench/sites/$site_name/site_config.json' && chmod 640 '/home/frappe/frappe-bench/sites/$site_name/site_config.json'"
  fi
  docker exec "$backend_id" rm -rf "$remote_dir"
  docker compose -f "$compose_file" up -d --force-recreate --wait
  docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
    bench --site "$site_name" clear-cache
}

case "$mode" in
  prepare) prepare_release ;;
  rollback) rollback_release ;;
  *) echo "Unknown mode: $mode" >&2; exit 2 ;;
esac
