#!/usr/bin/env bash
# Serialized bounded joint release; the frozen base retains CRM and Finance.
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
# This frozen joint release retains the already-deployed CRM/Finance packages.
[[ -z "$crm_archive" && -z "$finance_archive" ]] || { echo 'Joint release forbids additional app overlays' >&2; exit 1; }
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
retarget_existing_source_sync() {
  # Never enable a timer that was absent or stopped before this release.
  (( source_sync_timer_active )) || return 0
  local image_id=$1 runner_sha
  runner_sha=$(sha256sum "$build_dir/deeplinkerp_branding/services/dedicated_source_sync.py")
  runner_sha=${runner_sha%% *}
  python3 "$build_dir/deploy/production/dedicated_source_sync.py" install \
    --revision "$branding_sha" --image-id "$image_id" --runner-sha256 "$runner_sha" --start-timer
  systemctl --user is-enabled --quiet deeplinkerp-source-sync.timer
  systemctl --user is-active --quiet deeplinkerp-source-sync.timer
}
capture_pinned_sources() {
  docker run --rm --read-only --network none --entrypoint /home/frappe/frappe-bench/env/bin/python "$1" -c '
import hashlib,json
from pathlib import Path
result={}
for app in ("deeplinkerp_branding","china_finance","crm_integration"):
 root=Path("/home/frappe/frappe-bench/apps")/app/app
 assert root.is_dir(), "Missing pinned app source: "+app
 result[app]={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc",".pyo"}}
print(json.dumps(result))
' > "$2"
}
capture_release_audit() {
  # Private backups keep the release umask; only copied source tools are readable.
  chmod 644 "$build_dir/deploy/production/audit_unified_purchase.py" || return 1
  chmod 644 "$build_dir/deploy/production/procurement_release_metadata.py" || return 1
  chmod 644 "$build_dir/deploy/production/joint_release_guards.py" || return 1
  chmod 644 "$build_dir/deeplinkerp_branding/deeplinkerp_branding/page/purchase_payment_records/purchase_payment_records.json" || return 1
  docker cp "$build_dir/deploy/production/audit_unified_purchase.py" frappe_docker-backend-1:/tmp/audit_unified_purchase.py || return 1
  docker cp "$build_dir/deploy/production/procurement_release_metadata.py" frappe_docker-backend-1:/tmp/procurement_release_metadata.py || return 1
  docker cp "$build_dir/deploy/production/joint_release_guards.py" frappe_docker-backend-1:/tmp/joint_release_guards.py || return 1
  docker cp "$build_dir/deeplinkerp_branding/deeplinkerp_branding/page/purchase_payment_records/purchase_payment_records.json" frappe_docker-backend-1:/tmp/purchase-payment-records.json || return 1
  if [[ -f "$build_dir/release-source-manifest.json" ]]; then
    chmod 644 "$build_dir/release-source-manifest.json" || return 1
    docker cp "$build_dir/release-source-manifest.json" frappe_docker-backend-1:/tmp/release-source-manifest.json || return 1
  fi
  local receipt_args=()
  local quiescent=1
  if [[ "$1" == current ]]; then quiescent=0; fi
  if [[ "$1" == after ]]; then receipt_args=(--joint-receipt "$native_receipt"); fi
  "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 -e "DEEPLINKERP_RELEASE_QUIESCENT=$quiescent" backend /home/frappe/frappe-bench/env/bin/python /tmp/audit_unified_purchase.py "${audit_args[@]}" "${receipt_args[@]}" --phase "$1" > "$2"
}
quiesce_release_workers() {
  "${dc[@]}" stop queue-long queue-short scheduler || return 1
  local service
  for service in queue-long queue-short scheduler; do
    test "$(docker inspect "frappe_docker-$service-1" --format '{{.State.Running}}')" = false || return 1
  done
}
verify_staged_release() {
  local image_id=$1 branding=$2 crm=$3 finance=$4 service running label
  for service in "${services[@]}"; do
    test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$image_id" || return 1
    label=$(revision_label "frappe_docker-$service-1" branding) || return 1
    test "$label" = "$branding" || return 1
    label=$(revision_label "frappe_docker-$service-1" crm) || return 1
    test "$label" = "$crm" || return 1
    label=$(revision_label "frappe_docker-$service-1" finance) || return 1
    test "$label" = "$finance" || return 1
    running=$(docker inspect "frappe_docker-$service-1" --format '{{.State.Running}}') || return 1
    case "$service" in queue-long|queue-short|scheduler) test "$running" = false || return 1;;
      *) test "$running" = true || return 1;; esac
  done
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
		        'deploy/production/procurement_release_metadata.py',
                'deploy/production/joint_release_guards.py',
                'deploy/production/dedicated_source_sync.py',
                'deploy/production/systemd/deeplinkerp-source-sync.service',
                'deploy/production/systemd/deeplinkerp-source-sync.timer',
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
# Parse supported staging flags before building or enabling maintenance.
"${dc[@]}" up --no-start --force-recreate --no-deps --help > /dev/null
services=(backend frontend queue-long queue-short scheduler websocket)
build_dir=$(mktemp -d /tmp/unified-purchase-build.XXXXXX)
prepare_sources
source_sync_timer_active=0
source_sync_status=0
source_sync_state=$(systemctl --user is-active deeplinkerp-source-sync.timer) || source_sync_status=$?
case "$source_sync_state:$source_sync_status" in
  active:0)
    test -s /home/yuewei/.local/state/deeplinkerp-source-sync/config.json
    source_sync_timer_active=1
    ;;
  inactive:3) ;;
  unknown:4)
    test ! -e /home/yuewei/.local/state/deeplinkerp-source-sync/config.json
    ;;
  *) echo 'Existing source timer state is unconfirmed; cutover refused.' >&2; exit 1;;
esac
current_revision=$(revision_label frappe_docker-backend-1 branding)
current_crm=$(revision_label frappe_docker-backend-1 crm)
current_finance=$(revision_label frappe_docker-backend-1 finance)
if [[ -z "$crm_archive" ]]; then crm_sha=$current_crm; fi
if [[ -z "$finance_archive" ]]; then finance_sha=$current_finance; fi
if release_is_current; then
  curl -fsS --max-time 10 https://deeplinkerp.com/api/method/ping
  current_image_id=$(docker inspect frappe_docker-backend-1 --format '{{.Image}}')
  audit_args=(--purchase-payment-page-source /tmp/purchase-payment-records.json --joint-metadata --release-manifest /tmp/release-source-manifest.json)
  capture_release_audit current "$build_dir/current-contract.json"
  capture_pinned_sources "$current_image_id" "$build_dir/current-image-sources.json"
  python3 - "$build_dir/current-contract.json" "$build_dir/current-image-sources.json" <<'PY'
import json, sys
current = json.load(open(sys.argv[1]))
assert current['current_contract_verified'] is True
assert current['release_sources_all'] == json.load(open(sys.argv[2])), 'Running app source differs from current immutable image'
PY
  # The same revision may need its timer pins repaired after an interrupted handoff.
  flock -u 9
  retarget_existing_source_sync "$current_image_id"
  release_is_current
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
release_dir="private/release-evidence/unified-purchase-$release_key"
native_receipt="/home/frappe/frappe-bench/sites/deeplinkerp.com/private/release-evidence/joint-$release_key.json"
mkdir -p private/release-evidence
mkdir "$release_dir" # Refuse an ambiguous repeated cutover; retain previous evidence.
cp compose.custom.yaml "$release_dir/compose.before.yaml"
audit_args=(--purchase-payment-page-source /tmp/purchase-payment-records.json --joint-metadata)
if [[ -f "$build_dir/release-source-manifest.json" ]]; then
  chmod 644 "$build_dir/release-source-manifest.json"
  audit_args+=(--release-manifest /tmp/release-source-manifest.json)
fi
# The private release umask is right for backups, not for a script copied as root to a non-root container.
chmod 644 "$build_dir/deeplinkerp_branding/deeplinkerp_branding/page/purchase_payables/purchase_payables.json"
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
maintenance=0
switched=0
baseline_captured=0
recover() {
  code=$?
  if (( code != 0 )); then
    recovery_ok=1
    quiesce_release_workers || recovery_ok=0
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
          "${dc[@]}" up -d --no-deps backend frontend websocket || recovery_ok=0
          "${dc[@]}" up --no-start --force-recreate --no-deps queue-long queue-short scheduler || recovery_ok=0
        fi
        for service in "${services[@]}"; do
          test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$old_image_id" || recovery_ok=0
        done
        verify_staged_release "$old_image_id" "$current_revision" "$current_crm" "$current_finance" || recovery_ok=0
        if "${dc[@]}" exec -T backend test -s "$native_receipt"; then
          docker cp "$build_dir/deploy/production/procurement_release_metadata.py" frappe_docker-backend-1:/tmp/procurement_release_metadata.py || recovery_ok=0
          docker cp "$build_dir/deploy/production/joint_release_guards.py" frappe_docker-backend-1:/tmp/joint_release_guards.py || recovery_ok=0
          docker cp "$build_dir/deploy/production/audit_unified_purchase.py" frappe_docker-backend-1:/tmp/audit_unified_purchase.py || recovery_ok=0
          if (( recovery_ok )); then
            "${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 -e DEEPLINKERP_RELEASE_QUIESCENT=1 backend /home/frappe/frappe-bench/env/bin/python /tmp/procurement_release_metadata.py --joint-rollback --receipt "$native_receipt" --candidate-sha "$branding_sha" --source-phase before > "$release_dir/metadata-rollback.json" || recovery_ok=0
            docker cp "frappe_docker-backend-1:$native_receipt" "$release_dir/joint-receipt.json" || recovery_ok=0
          fi
        fi
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
before.pop('approved_sources_after', None)
rollback = json.loads((root / 'rollback.json').read_text())
assert before == rollback, 'Restored audit differs from original baseline; maintenance retained'
print('Restored full audit matches original baseline')
PY
      then recovery_ok=0; fi
    fi
    if (( recovery_ok )); then
      "${dc[@]}" up -d --no-deps "${services[@]}" || recovery_ok=0
      verify_running_release "$old_image_id" "$current_revision" "$current_crm" "$current_finance" || recovery_ok=0
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
quiesce_release_workers
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com backup --with-files --compress > "$release_dir/backup.log"
capture_release_audit before "$release_dir/before.json"
baseline_captured=1
# Compare complete running source sets against the pinned immutable image, then
# freeze the complete candidate Branding package and unchanged CRM/Finance sets.
capture_pinned_sources "$old_image_id" "$release_dir/pinned-base-sources.json"
python3 - "$release_dir" "$build_dir" <<'PY'
import hashlib,json,sys
from pathlib import Path
evidence,build=map(Path,sys.argv[1:])
sys.path.insert(0,str(build/'deploy/production'))
from joint_release_guards import merge_frozen_branding_sources
before=json.loads((evidence/'before.json').read_text())
assert before['release_sources_all']==json.loads((evidence/'pinned-base-sources.json').read_text()), 'Running app source differs from pinned base image'
candidate=build/'deeplinkerp_branding'
after=dict(before['release_sources_all'])
candidate_files={str(p.relative_to(candidate)):hashlib.sha256(p.read_bytes()).hexdigest() for p in candidate.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
after['deeplinkerp_branding']=merge_frozen_branding_sources(before['release_sources_all']['deeplinkerp_branding'],candidate_files)
before['approved_sources_after']=after
(evidence/'before.json').write_text(json.dumps(before,sort_keys=True,ensure_ascii=False))
PY
cp "$release_dir/compose.after.yaml" compose.custom.yaml
switched=1
"${dc[@]}" config --quiet
"${dc[@]}" up -d --no-deps backend frontend websocket
"${dc[@]}" up --no-start --force-recreate --no-deps queue-long queue-short scheduler
verify_staged_release "$new_image_id" "$branding_sha" "$crm_sha" "$finance_sha"
docker cp "$build_dir/deploy/production/procurement_release_metadata.py" frappe_docker-backend-1:/tmp/procurement_release_metadata.py
docker cp "$build_dir/deeplinkerp_branding/deeplinkerp_branding/page/purchase_payables/purchase_payables.json" frappe_docker-backend-1:/tmp/purchase-payables.json
docker cp "$release_dir/before.json" frappe_docker-backend-1:/tmp/procurement-before-audit.json
docker exec --user root frappe_docker-backend-1 chown frappe:frappe /tmp/procurement-before-audit.json
# One bounded installer, with its first fsynced receipt in the shared sites volume.
docker cp "$build_dir/deploy/production/joint_release_guards.py" frappe_docker-backend-1:/tmp/joint_release_guards.py
docker cp "$build_dir/deploy/production/audit_unified_purchase.py" frappe_docker-backend-1:/tmp/audit_unified_purchase.py
"${dc[@]}" exec -T backend mkdir -p /home/frappe/frappe-bench/sites/deeplinkerp.com/private/release-evidence
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 -e DEEPLINKERP_RELEASE_QUIESCENT=1 backend /home/frappe/frappe-bench/env/bin/python /tmp/procurement_release_metadata.py --joint-apply --receipt "$native_receipt" --candidate-sha "$branding_sha" --before-audit /tmp/procurement-before-audit.json > "$release_dir/metadata.json"
docker cp "frappe_docker-backend-1:$native_receipt" "$release_dir/joint-receipt.json"
# Frappe's lazy require cache version is the manifest mtime. Preserve its contents/bundles.
"${dc[@]}" exec -T backend touch /home/frappe/frappe-bench/sites/assets/assets.json
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com clear-cache
capture_release_audit after "$release_dir/after.json"
python3 - "$release_dir" "$build_dir" <<'PY'
import json
import runpy
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0,str(Path(sys.argv[2], 'deploy/production')))
before = json.loads((root / 'before.json').read_text())
after = json.loads((root / 'after.json').read_text())
metadata = runpy.run_path(str(Path(sys.argv[2], 'deploy/production/procurement_release_metadata.py')))
metadata['verify_joint_audit_delta'](before, after, json.loads((root / 'joint-receipt.json').read_text()))
print('Business data and preserved application hashes unchanged')
PY
"${dc[@]}" up -d --no-deps "${services[@]}"
verify_running_release "$new_image_id" "$branding_sha" "$crm_sha" "$finance_sha"
"${dc[@]}" exec -T -e FRAPPE_STREAM_LOGGING=1 backend bench --site deeplinkerp.com set-maintenance-mode off
maintenance=0
for attempt in $(seq 1 90); do
  if curl -fsS --max-time 10 https://deeplinkerp.com/api/method/ping; then break; fi
  if (( attempt == 90 )); then exit 1; fi
  sleep 1
done
# Cutover is verified; the timer installer acquires the same mutex itself.
# Once unlocked, a source job may write. Never run the pre-cutover rollback trap
# after this boundary; report an unconfirmed handoff without reverting live data.
trap - EXIT
flock -u 9
retarget_existing_source_sync "$new_image_id"
release_is_current
docker inspect frappe_docker-backend-1 --format '{{.Config.Image}} {{.Image}}'
printf '\nApp cutover verified; logged-in UI acceptance still required.\n'
