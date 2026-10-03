#!/usr/bin/env bash
# Brand-only serialized release; one new Page reload, no migrate or business writes.
set -euo pipefail
umask 077
archive=${1:?Committed source archive required}
branding_sha=${2:?Full branding commit required}
old_image=${3:?Verified running base image required}
old_image_id=${4:?Verified running base image ID required}
[[ "$branding_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$archive" == /tmp/deeplinkerp-unified-purchase-*.tar.gz ]]
test -s "$archive"
cd /home/yuewei/ERPNext-Docker/frappe_docker
exec 9>/tmp/deeplinkerp-erp-release.lock
flock -n 9 || { echo 'Another ERP release owns the lock'; exit 1; }
dc=(docker compose -p frappe_docker -f compose.custom.yaml)
services=(backend frontend queue-long queue-short scheduler websocket)
for service in "${services[@]}"; do
  test "$(docker inspect "frappe_docker-$service-1" --format '{{.Config.Image}}')" = "$old_image"
  test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$old_image_id"
done
test "$(docker image inspect "$old_image" --format '{{.Id}}')" = "$old_image_id"
release_dir="backups/unified-purchase-${branding_sha:0:12}"
mkdir "$release_dir" # Refuse an ambiguous repeated cutover; retain previous evidence.
cp compose.custom.yaml "$release_dir/compose.before.yaml"
build_dir=$(mktemp -d /tmp/unified-purchase-build.XXXXXX)
tar -xzf "$archive" -C "$build_dir"
# The private release umask is right for backups, not for a script copied as root to a non-root container.
chmod 644 "$build_dir/deploy/production/audit_unified_purchase.py"
new_image="deeplinkerp-custom:unified-purchase-${branding_sha:0:12}"
frozen_base="deeplinkerp-custom:unified-base-${branding_sha:0:12}"
docker image tag "$old_image_id" "$frozen_base"
test "$(docker image inspect "$frozen_base" --format '{{.Id}}')" = "$old_image_id"
docker build --build-arg "BASE_IMAGE=$frozen_base" --build-arg "BRANDING_SHA=$branding_sha" \
  -f "$build_dir/deploy/local/Dockerfile.unified-purchase" -t "$new_image" "$build_dir"
test "$(docker image inspect "$new_image" --format '{{index .Config.Labels "org.deeplinkerp.branding.revision"}}')" = "$branding_sha"
new_image_id=$(docker image inspect "$new_image" --format '{{.Id}}')
python3 - "$old_image" "$new_image" "$release_dir" "$frozen_base" <<'PY'
import sys
from pathlib import Path
source = Path('compose.custom.yaml').read_text()
assert source.count(sys.argv[1]) == 7, 'Unexpected Compose baseline'
Path(sys.argv[3], 'compose.after.yaml').write_text(source.replace(sys.argv[1], sys.argv[2]))
Path(sys.argv[3], 'compose.rollback.yaml').write_text(source.replace(sys.argv[1], sys.argv[4]))
PY
maintenance=0
switched=0
recover() {
  code=$?
  if (( code != 0 )); then
    recovery_ok=1
    # Keep the shared maintenance flag on until every service has a verified frozen revision.
    maintenance_set=0
    if "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode on; then
      maintenance_set=1
    else
      # A dead new backend must not prevent host-side restoration of the good image.
      docker stop frappe_docker-frontend-1 || true
    fi
    if (( switched )); then
      test "$(docker image inspect "$frozen_base" --format '{{.Id}}')" = "$old_image_id" || recovery_ok=0
      if (( recovery_ok )); then
        cp "$release_dir/compose.rollback.yaml" compose.custom.yaml || recovery_ok=0
        "${dc[@]}" up -d --no-deps backend || recovery_ok=0
        if "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode on; then
          maintenance_set=1
        else
          recovery_ok=0
        fi
        if (( recovery_ok )); then
          "${dc[@]}" up -d --no-deps "${services[@]}" || recovery_ok=0
        fi
        for service in "${services[@]}"; do
          test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$old_image_id" || recovery_ok=0
          test "$(docker inspect "frappe_docker-$service-1" --format '{{.State.Running}}')" = true || recovery_ok=0
        done
        "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com clear-cache || recovery_ok=0
      fi
    fi
    if (( ! maintenance_set )); then recovery_ok=0; fi
    if (( recovery_ok )); then
      "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode off || recovery_ok=0
      if (( recovery_ok )); then
        health_ok=0
        for attempt in $(seq 1 10); do
          if curl -fsS https://deeplinkerp.com/api/method/ping; then health_ok=1; break; fi
          sleep 1
        done
        if (( ! health_ok )); then
          recovery_ok=0
          "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode on || true
        fi
      fi
    fi
    if (( ! recovery_ok )); then
      docker stop frappe_docker-frontend-1 || true
      echo 'Rollback could not be verified; maintenance remains enabled. Manual recovery required.' >&2
    fi
  fi
  exit "$code"
}
trap recover EXIT
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode on
maintenance=1
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com ready-for-migration
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com backup > "$release_dir/backup.log"
docker cp "$build_dir/deploy/production/audit_unified_purchase.py" frappe_docker-backend-1:/tmp/audit-unified-purchase.py
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend /home/frappe/frappe-bench/env/bin/python /tmp/audit-unified-purchase.py > "$release_dir/before.json"
cp "$release_dir/compose.after.yaml" compose.custom.yaml
switched=1
"${dc[@]}" config --quiet
"${dc[@]}" up -d --no-deps "${services[@]}"
for service in "${services[@]}"; do
  test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$new_image_id"
  test "$(docker inspect "frappe_docker-$service-1" --format '{{.State.Running}}')" = true
done
docker cp "$build_dir/deploy/production/audit_unified_purchase.py" frappe_docker-backend-1:/tmp/audit-unified-purchase.py
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com reload-doc deeplinkerp_branding page purchase_payment_records
# Frappe's lazy require cache version is the manifest mtime. Preserve its contents/bundles.
"${dc[@]}" exec -T backend touch /home/frappe/frappe-bench/sites/assets/assets.json
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com clear-cache
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend /home/frappe/frappe-bench/env/bin/python /tmp/audit-unified-purchase.py > "$release_dir/after.json"
python3 - "$release_dir" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
before = json.loads((root / 'before.json').read_text())
after = json.loads((root / 'after.json').read_text())
assert before == after, 'Business data, preserved apps, or asset manifest changed; release rejected'
print('Business data and preserved application hashes unchanged')
PY
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode off
maintenance=0
for attempt in $(seq 1 90); do
  if curl -fsS https://deeplinkerp.com/api/method/ping; then break; fi
  if (( attempt == 90 )); then exit 1; fi
  sleep 1
done
docker inspect frappe_docker-backend-1 --format '{{.Config.Image}} {{.Image}}'
printf '\nBrand-only cutover verified; logged-in UI acceptance still required.\n'
