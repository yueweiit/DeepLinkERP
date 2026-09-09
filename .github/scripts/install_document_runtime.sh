#!/usr/bin/env bash
set -euo pipefail

compose_root="${1:-/home/yuewei/ERPNext-Docker/frappe_docker}"
site_name="${2:-deeplinkerp.com}"
dockerfile_path="${3:?material AI runtime Containerfile is required}"
release_id="${4:-manual}"
mode="${5:-install}"
compose_file="$compose_root/compose.custom.yaml"
base_image="deeplinkerp-custom:v16.23.0-latest"
runtime_image="deeplinkerp-custom:material-ai-$release_id"
backup_image="deeplinkerp-custom:pre-material-ai-runtime-$release_id"

cd "$compose_root"
docker image inspect "$base_image" >/dev/null

verify_runtime_image() {
  docker run --rm --entrypoint sh "$1" -lc '
    command -v pdftotext >/dev/null
    command -v pdftoppm >/dev/null
    command -v tesseract >/dev/null
    command -v antiword >/dev/null
    tesseract --list-langs 2>/dev/null | grep -Fx chi_sim >/dev/null
  '
}

if [ "$mode" = "preflight" ]; then
  docker build \
    --build-arg "BASE_IMAGE=$base_image" \
    --file "$dockerfile_path" \
    --tag "$runtime_image-preflight" \
    .
  verify_runtime_image "$runtime_image-preflight"
  exit 0
fi

[ "$mode" = "install" ] || { echo "Unknown runtime mode: $mode" >&2; exit 2; }
docker image tag "$base_image" "$backup_image"
docker compose -f "$compose_file" exec -T -w /home/frappe/frappe-bench backend \
  bench --site "$site_name" backup --with-files

rollback_runtime() {
  docker image tag "$backup_image" "$base_image"
  docker compose -f "$compose_file" up -d --no-deps --force-recreate \
    backend queue-short queue-long scheduler
  docker compose -f "$compose_file" restart frontend
}
trap rollback_runtime ERR

docker build \
  --build-arg "BASE_IMAGE=$base_image" \
  --file "$dockerfile_path" \
  --tag "$runtime_image" \
  .
docker image tag "$runtime_image" "$base_image"
docker compose -f "$compose_file" up -d --no-deps --force-recreate \
  backend queue-short queue-long scheduler
docker compose -f "$compose_file" restart frontend
verify_runtime_image "$base_image"

trap - ERR
