#!/usr/bin/env bash
# Serialized app release. Optional CRM and Finance overlays use a source-drift manifest.
set -euo pipefail
umask 077
archive=${1:?Committed source archive required}
branding_sha=${2:?Full branding commit required}
old_image=${3:?Verified running base image required}
old_image_id=${4:?Verified running base image ID required}
crm_archive=${5:-}
crm_sha=${6:-}
finance_archive=${7:-}
finance_sha=${8:-}
if [[ -n "$crm_archive" ]]; then
  [[ "$crm_sha" =~ ^[0-9a-f]{40}$ ]]
  [[ "$crm_archive" == /tmp/deeplinkerp-sales-crm-*.tar.gz ]]
  test -s "$crm_archive"
fi
if [[ -n "$finance_archive" ]]; then
  [[ "$finance_sha" =~ ^[0-9a-f]{40}$ ]]
  [[ "$finance_archive" == /tmp/deeplinkerp-finance-*.tar.gz ]]
  test -s "$finance_archive"
fi
[[ "$branding_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$archive" == /tmp/deeplinkerp-unified-purchase-*.tar.gz ]]
test -s "$archive"
revision_label() {
  local value
  value=$(docker inspect "$1" --format "{{index .Config.Labels \"org.deeplinkerp.$2.revision\"}}") || return 1
  if [[ "$value" != '<no value>' ]]; then printf '%s' "$value"; fi
}
verify_running_release() {
  local image_id=$1 branding=$2 crm=$3 finance=$4 service label
  for service in "${services[@]}"; do
    test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$image_id" || return 1
    test "$(docker inspect "frappe_docker-$service-1" --format '{{.State.Running}}')" = true || return 1
    label=$(revision_label "frappe_docker-$service-1" branding) || return 1
    test "$label" = "$branding" || return 1
    label=$(revision_label "frappe_docker-$service-1" crm) || return 1
    test "$label" = "$crm" || return 1
    label=$(revision_label "frappe_docker-$service-1" finance) || return 1
    test "$label" = "$finance" || return 1
  done
}
release_is_current() {
  local image_id
  image_id=$(docker inspect frappe_docker-backend-1 --format '{{.Image}}') || return 1
  verify_running_release "$image_id" "$branding_sha" "$crm_sha" "$finance_sha"
}
prepare_sources() {
  python3 - "$build_dir" "$archive" "$crm_archive" "$finance_archive" <<'PY'
import hashlib
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1])
finance_files = {'services/cash_flow_assignment.py', 'services/voucher.py', 'tests/test_cancellation_sync.py',
                 'tests/test_cancellation_sync_concurrency.py', 'translations/zh.csv'}
deploy_files = {'deploy/production/deploy_unified_purchase.sh', 'deploy/production/audit_unified_purchase.py',
                'deploy/local/Dockerfile.unified-purchase'}
archives = []
manifest = None
overlaid = {'deeplinkerp_branding'}
for kind, archive in zip(('branding', 'crm', 'finance'), sys.argv[2:]):
    if not archive:
        continue
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        seen = set()
        files_seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and '\\' not in member.name, 'Unsafe archive path'
            assert str(path) == member.name.rstrip('/') and path.parts, 'Invalid archive path'
            assert member.isdir() or member.isfile(), 'Archive links and special files are forbidden'
            assert str(path) not in seen, 'Duplicate archive entry'
            seen.add(str(path))
            if member.isdir():
                name = str(path)
                if kind == 'branding':
                    assert name == 'deeplinkerp_branding' or name.startswith('deeplinkerp_branding/') or any(path in PurePosixPath(file).parents for file in deploy_files), 'Unexpected Branding archive directory'
                elif kind == 'crm':
                    assert name in {'crm-overlay', 'crm-overlay/crm_integration'} or name.startswith('crm-overlay/crm_integration/'), 'Unexpected CRM archive directory'
                else:
                    assert any(path in PurePosixPath('finance-overlay/china_finance/' + file).parents for file in finance_files), 'Unexpected Finance archive directory'
                continue
            files_seen.add(member.name)
            if member.name == 'release-source-manifest.json':
                candidate = json.load(tar.extractfile(member))
                assert manifest is None or manifest == candidate, 'Conflicting release manifests'
                manifest = candidate
                continue
            if kind == 'branding':
                assert member.name.startswith('deeplinkerp_branding/') or member.name in deploy_files, 'Unexpected Branding archive file'
            elif kind == 'crm':
                assert member.name.startswith('crm-overlay/crm_integration/'), 'Unexpected CRM archive file'
            else:
                assert member.name in {'finance-overlay/china_finance/' + path for path in finance_files}, 'Unexpected Finance archive file'
        archives.append((archive, [member for member in members if member.name != 'release-source-manifest.json']))
        if kind != 'branding':
            overlaid.add({'crm': 'crm_integration', 'finance': 'china_finance'}[kind])
        if kind == 'finance':
            assert files_seen - {'release-source-manifest.json'} == {'finance-overlay/china_finance/' + path for path in finance_files}, 'Incomplete Finance overlay'
if len(overlaid) > 1:
    assert manifest is not None, 'Optional app overlays require a release manifest'
if manifest is not None:
    assert set(manifest['apps']) == overlaid, 'Manifest app set differs from overlays'
    if 'china_finance' in overlaid:
        assert set(manifest['apps']['china_finance']) == finance_files, 'Unexpected Finance manifest files'
    for app, files in manifest['apps'].items():
        assert files, 'Empty app manifest'
        for name in files:
            path = PurePosixPath(name)
            assert name and not path.is_absolute() and '..' not in path.parts and '\\' not in name
            assert str(path) == name and path.parts, 'Invalid manifest path'
for archive, members in archives:
    with tarfile.open(archive, 'r:gz') as tar:
        tar.extractall(root, members=members)
for directory in ('crm-overlay', 'finance-overlay'):
    (root / directory).mkdir(exist_ok=True)
if manifest is not None:
    for app, files in manifest['apps'].items():
        prefix = {'deeplinkerp_branding': 'deeplinkerp_branding', 'crm_integration': 'crm-overlay/crm_integration',
                  'china_finance': 'finance-overlay/china_finance'}[app]
        for name, versions in files.items():
            candidate = root / prefix / name
            assert candidate.is_file(), f'Missing candidate source: {app}/{name}'
            assert hashlib.sha256(candidate.read_bytes()).hexdigest() == versions['after'], f'Candidate source drift: {app}/{name}'
    (root / 'release-source-manifest.json').write_text(json.dumps(manifest, sort_keys=True))
PY
}
cd /home/yuewei/ERPNext-Docker/frappe_docker
exec 9>/tmp/deeplinkerp-erp-release.lock
flock -n 9 || { echo 'Another ERP release owns the lock'; exit 1; }
dc=(docker compose -p frappe_docker -f compose.custom.yaml)
services=(backend frontend queue-long queue-short scheduler websocket)
build_dir=$(mktemp -d /tmp/unified-purchase-build.XXXXXX)
prepare_sources
current_revision=$(revision_label frappe_docker-backend-1 branding)
current_crm=$(revision_label frappe_docker-backend-1 crm)
current_finance=$(revision_label frappe_docker-backend-1 finance)
if [[ -z "$crm_archive" ]]; then crm_sha=$current_crm; fi
if [[ -z "$finance_archive" ]]; then finance_sha=$current_finance; fi
if release_is_current; then
  curl -fsS --max-time 10 https://deeplinkerp.com/api/method/ping
  echo 'Target revision already running; no repeated cutover.'
  exit 0
fi
for service in "${services[@]}"; do
  test "$(docker inspect "frappe_docker-$service-1" --format '{{.Config.Image}}')" = "$old_image"
  test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$old_image_id"
done
verify_running_release "$old_image_id" "$current_revision" "$current_crm" "$current_finance"
test "$(docker image inspect "$old_image" --format '{{.Id}}')" = "$old_image_id"
release_key=${branding_sha:0:12}
if [[ -n "$crm_archive" ]]; then release_key+="-crm-${crm_sha:0:12}"; fi
if [[ -n "$finance_archive" ]]; then release_key+="-finance-${finance_sha:0:12}"; fi
release_dir="backups/unified-purchase-$release_key"
mkdir "$release_dir" # Refuse an ambiguous repeated cutover; retain previous evidence.
cp compose.custom.yaml "$release_dir/compose.before.yaml"
audit_args=()
if [[ -f "$build_dir/release-source-manifest.json" ]]; then
  chmod 644 "$build_dir/release-source-manifest.json"
  audit_args=(--release-manifest /tmp/release-source-manifest.json)
fi
# The private release umask is right for backups, not for a script copied as root to a non-root container.
chmod 644 "$build_dir/deploy/production/audit_unified_purchase.py"
new_image="deeplinkerp-custom:unified-purchase-$release_key"
frozen_base="deeplinkerp-custom:unified-base-$release_key"
docker image tag "$old_image_id" "$frozen_base"
test "$(docker image inspect "$frozen_base" --format '{{.Id}}')" = "$old_image_id"
docker build --build-arg "BASE_IMAGE=$frozen_base" --build-arg "BRANDING_SHA=$branding_sha" --build-arg "CRM_SHA=$crm_sha" --build-arg "FINANCE_SHA=$finance_sha" \
  -f "$build_dir/deploy/local/Dockerfile.unified-purchase" -t "$new_image" "$build_dir"
test "$(docker image inspect "$new_image" --format '{{index .Config.Labels "org.deeplinkerp.branding.revision"}}')" = "$branding_sha"
test "$(docker image inspect "$new_image" --format '{{index .Config.Labels "org.deeplinkerp.crm.revision"}}')" = "$crm_sha"
test "$(docker image inspect "$new_image" --format '{{index .Config.Labels "org.deeplinkerp.finance.revision"}}')" = "$finance_sha"
new_image_id=$(docker image inspect "$new_image" --format '{{.Id}}')
python3 - "$old_image" "$new_image" "$release_dir" "$frozen_base" <<'PY'
import sys
from pathlib import Path
source = Path('compose.custom.yaml').read_text()
assert source.count(sys.argv[1]) == 7, 'Unexpected Compose baseline'
Path(sys.argv[3], 'compose.after.yaml').write_text(source.replace(sys.argv[1], sys.argv[2]))
Path(sys.argv[3], 'compose.rollback.yaml').write_text(source.replace(sys.argv[1], sys.argv[4]))
PY
capture_release_audit() {
  docker cp "$build_dir/deploy/production/audit_unified_purchase.py" frappe_docker-backend-1:/tmp/audit-unified-purchase.py || return 1
  if [[ -f "$build_dir/release-source-manifest.json" ]]; then
    docker cp "$build_dir/release-source-manifest.json" frappe_docker-backend-1:/tmp/release-source-manifest.json || return 1
  fi
  "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend /home/frappe/frappe-bench/env/bin/python /tmp/audit-unified-purchase.py "${audit_args[@]}" --phase "$1" > "$2"
}
maintenance=0
switched=0
baseline_captured=0
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
    if (( ! baseline_captured )) || [[ ! -s "$release_dir/before.json" ]]; then recovery_ok=0; fi
    if (( recovery_ok )); then
      capture_release_audit before "$release_dir/rollback.json" || recovery_ok=0
    fi
    if (( recovery_ok )); then
      if ! python3 - "$release_dir" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
before = json.loads((root / 'before.json').read_text())
rollback = json.loads((root / 'rollback.json').read_text())
assert before == rollback, 'Restored audit differs from original baseline; maintenance retained'
print('Restored full audit matches original baseline')
PY
      then recovery_ok=0; fi
    fi
    if (( recovery_ok )); then
      "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode off || recovery_ok=0
      if (( recovery_ok )); then
        health_ok=0
        for attempt in $(seq 1 90); do
          if curl -fsS --max-time 10 https://deeplinkerp.com/api/method/ping; then health_ok=1; break; fi
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
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com backup --with-files --compress > "$release_dir/backup.log"
capture_release_audit before "$release_dir/before.json"
baseline_captured=1
cp "$release_dir/compose.after.yaml" compose.custom.yaml
switched=1
"${dc[@]}" config --quiet
"${dc[@]}" up -d --no-deps "${services[@]}"
verify_running_release "$new_image_id" "$branding_sha" "$crm_sha" "$finance_sha"
if [[ -n "$crm_archive" ]]; then
  # Register only the new empty capability metadata; do not run unrelated app migrations.
  "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com reload-doc crm_integration doctype sales_production_release_permission
fi
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com reload-doc deeplinkerp_branding page purchase_payment_records
# Frappe's lazy require cache version is the manifest mtime. Preserve its contents/bundles.
"${dc[@]}" exec -T backend touch /home/frappe/frappe-bench/sites/assets/assets.json
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com clear-cache
capture_release_audit after "$release_dir/after.json"
python3 - "$release_dir" "$build_dir" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
before = json.loads((root / 'before.json').read_text())
after = json.loads((root / 'after.json').read_text())
manifest_path = Path(sys.argv[2], 'release-source-manifest.json')
if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text())
    old_sources = before.pop('release_sources')
    new_sources = after.pop('release_sources')
    assert set(old_sources) == set(new_sources) == set(manifest['apps']), 'Unexpected audited source apps'
    for app, files in manifest['apps'].items():
        for path, versions in files.items():
            assert old_sources[app].get(path) == versions['before'], f'Unexpected before source: {app}/{path}'
            assert new_sources[app].get(path) == versions['after'], f'Unexpected after source: {app}/{path}'
        changed = {p for p in set(old_sources[app]) | set(new_sources[app]) if old_sources[app].get(p) != new_sources[app].get(p)}
        expected = {p for p, versions in files.items() if versions['before'] != versions['after']}
        assert changed == expected, f'Unexpected app source changes: {app}'
        # Remove only explicitly overlaid app digests; every other app remains in the equality audit.
        if app in before['preserved_apps']:
            before['preserved_apps'].pop(app)
            after['preserved_apps'].pop(app)
assert before == after, 'Business data, preserved apps, or asset manifest changed; release rejected'
print('Business data and preserved application hashes unchanged')
PY
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode off
maintenance=0
for attempt in $(seq 1 90); do
  if curl -fsS --max-time 10 https://deeplinkerp.com/api/method/ping; then break; fi
  if (( attempt == 90 )); then exit 1; fi
  sleep 1
done
docker inspect frappe_docker-backend-1 --format '{{.Config.Image}} {{.Image}}'
printf '\nApp cutover verified; logged-in UI acceptance still required.\n'
