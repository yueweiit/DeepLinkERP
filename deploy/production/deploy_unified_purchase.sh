#!/usr/bin/env bash
# Serialized bounded joint release; exact Finance/OA overlays retain every other app.
set -euo pipefail
umask 077
main_only=0
main_prepared=0
if [[ ${1:-} == --main-only ]]; then main_only=1; shift; fi
if [[ ${1:-} == --cleanup-owned-build ]]; then
  evidence=${2:?This release evidence directory required}
  acceptance=${3:?Actual online browser acceptance receipt required}
  cd /home/yuewei/ERPNext-Docker/frappe_docker
  exec 9>/tmp/deeplinkerp-erp-release.lock
  flock -n 9
  python3 - "$evidence" <<'PY'
import hashlib,json,os,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True)
assert root.parent==Path.cwd()/'private/release-evidence' and root.name.startswith('unified-purchase-') and root.stat().st_uid==os.getuid()
owned=json.loads((root/'build-ownership.json').read_bytes())
assert hashlib.sha256((root/'joint_release_guards.py').read_bytes()).hexdigest()==owned['guard_sha256'], 'Cleanup guard differs from this frozen release; forward HOLD'
if owned.get('lane')=='main-only': assert hashlib.sha256((root/'main_site_lane.py').read_bytes()).hexdigest()==owned['main_helper_sha256'], 'Cleanup main helper differs from this frozen release; forward HOLD'
PY
  python3 "$evidence/joint_release_guards.py" --cleanup-owned-build --evidence "$evidence" --acceptance "$acceptance"
  exit
fi
archive=${1:?Committed source archive required}
branding_sha=${2:?Full branding commit required}
old_image=${3:?Verified running base image required}
old_image_id=${4:?Verified running base image ID required}
crm_archive=${5:-}
crm_sha=${6:-}
finance_archive=${7:-}
finance_sha=${8:-}
oa_archive=${9:-}
oa_sha=${10:-}
approved_maintenance_sites=${11:-}
approved_native_schema_sites=${12:-}
if (( main_only )); then
  [[ -z "$approved_maintenance_sites" && -z "$approved_native_schema_sites" ]] || { echo '--main-only cannot authorize shared-site maintenance/schema' >&2; exit 1; }
else
[[ "$approved_maintenance_sites" == 'deeplinkerp.com,akivision.deeplinkerp.com,latingo.deeplinkerp.com,yuewei.deeplinkerp.com' ]] || {
  echo 'Four sites share serving containers. Main-only/unanswered maintenance approval is a scope blocker; no maintenance changed.' >&2; exit 1;
}
[[ "$approved_native_schema_sites" == 'akivision.deeplinkerp.com,latingo.deeplinkerp.com,yuewei.deeplinkerp.com' ]] || {
  echo 'Separate approval for exactly the three shared sites native fields/indexes/recover is required. No app installation or maintenance changed.' >&2; exit 1;
}
fi
# The final joint candidate overlays exactly Finance + OA and retains CRM.
[[ -z "$crm_archive" && -z "$crm_sha" ]] || { echo 'CRM must remain the independently verified base package' >&2; exit 1; }
[[ "$finance_sha" == b73f17138fdf8235e91a687b8a113cbb33e7031c && "$oa_sha" == cecb3b2c9e3c48217dbe127327ea8f2d5ee40ea7 ]]
[[ "$finance_archive" == /tmp/deeplinkerp-finance-*.tar.gz ]]
test -s "$finance_archive"
[[ "$oa_archive" == /tmp/deeplinkerp-oa-purchase-*.tar.gz ]]
test -s "$oa_archive"
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
  local image_id=$1 branding=$2 crm=$3 finance=$4 oa=${5:-} service label
  for service in "${services[@]}"; do
    test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$image_id" || return 1
    test "$(docker inspect "frappe_docker-$service-1" --format '{{.State.Running}}')" = true || return 1
    label=$(revision_label "frappe_docker-$service-1" branding) || return 1
    test "$label" = "$branding" || return 1
    label=$(revision_label "frappe_docker-$service-1" crm) || return 1
    test "$label" = "$crm" || return 1
    label=$(revision_label "frappe_docker-$service-1" finance) || return 1
    test "$label" = "$finance" || return 1
    label=$(revision_label "frappe_docker-$service-1" oa) || return 1
    test "$label" = "$oa" || return 1
  done
}
release_is_current() {
  (( ! ${main_only:-0} )) || return 1
  local image_id
  image_id=$(docker inspect frappe_docker-backend-1 --format '{{.Image}}') || return 1
  verify_running_release "$image_id" "$branding_sha" "$crm_sha" "$finance_sha" "$oa_sha"
}
retarget_existing_source_sync() {
  # Never enable a timer that was absent or stopped before this release.
  (( source_sync_timer_active )) || return 0
  local image_id=$1 target_revision=${2:-$branding_sha} runner_sha=${3:-}
  if [[ -z "$runner_sha" ]]; then
    runner_sha=$(sha256sum "$build_dir/deeplinkerp_branding/services/dedicated_source_sync.py")
    runner_sha=${runner_sha%% *}
  fi
  local launcher_args=(retarget --revision "$target_revision" --image-id "$image_id" --runner-sha256 "$runner_sha")
  if (( ${main_only:-0} )); then launcher_args+=(--container "${4:-deeplinkerp_main-backend-1}"); fi
  launcher_args+=(--start-timer)
  python3 "$build_dir/deploy/production/dedicated_source_sync.py" "${launcher_args[@]}"
  systemctl --user is-active --quiet deeplinkerp-source-sync.timer
}
capture_pinned_sources() {
  local image=$1 output=$2 apps=$3
  docker run --rm --read-only --network none --entrypoint /home/frappe/frappe-bench/env/bin/python "$image" -c '
import hashlib,json
from pathlib import Path
import sys
result={}
for app in json.loads(sys.argv[1]):
 root=Path("/home/frappe/frappe-bench/apps")/app/app
 assert root.is_dir(), "Missing pinned app source: "+app
 result[app]={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc",".pyo"}}
print(json.dumps(result))
' "$apps" > "$output"
}
command_runner() {
  local image=$1 entrypoint=$2
  shift 2
  if (( ${main_prepared:-0} )); then
    main_lane run --image-id "$image" --entrypoint "$entrypoint" --candidate-sha "$branding_sha" -- "$@"
    return
  fi
  main_lane runtime-access > /dev/null
  local drain_env=()
  if [[ -f "$release_dir/drain.json" ]]; then drain_env=(-e "DEEPLINKERP_RELEASE_DRAIN_RECEIPT=/release-evidence/drain.json"); fi
  docker run --rm --read-only --group-add "$private_runtime_gid" --network "$release_network" --workdir /home/frappe/frappe-bench/sites \
    --tmpfs /tmp --mount "type=bind,source=$build_dir,target=/release,readonly" \
    --mount "type=bind,source=$(pwd)/$release_dir,target=/release-evidence,readonly" \
    -v "$sites_spec:/home/frappe/frappe-bench/sites" \
    -e FRAPPE_STREAM_LOGGING=1 -e "DEEPLINKERP_RELEASE_CANDIDATE_SHA=$branding_sha" \
    "${drain_env[@]}" \
    -e "DEEPLINKERP_RELEASE_RESUME_RECEIPT=$resume_receipt" \
    --entrypoint "$entrypoint" "$image" "$@"
}
capture_release_audit() {
  local phase=$1 output=$2 image=${3:-$old_image_id} site=${4:-deeplinkerp.com}
  local receipt_args=() scope_args=() args=("${audit_args[@]}")
  local site_receipt="/home/frappe/frappe-bench/sites/$site/private/release-evidence/joint-${branding_sha:0:12}.json"
  if [[ "$site" != deeplinkerp.com ]]; then
    args=(--joint-metadata --release-manifest /release/release-source-manifest.json)
    scope_args=(--site "$site" --native-only)
  fi
  if [[ "$phase" == after ]]; then receipt_args=(--joint-receipt "$site_receipt"); fi
  command_runner "$image" /home/frappe/frappe-bench/env/bin/python /release/deploy/production/audit_unified_purchase.py \
    "${args[@]}" "${scope_args[@]}" "${receipt_args[@]}" --phase "$phase" > "$output"
}
quiesce_release_workers() {
  # The host guard records exact processes and a single native TERM intent.
  # Timeout/unknown outcome retains maintenance; never signal this identity again.
  python3 "$build_dir/deploy/production/joint_release_guards.py" --host-drain \
    --receipt "$release_dir/drain.json" --candidate-sha "$branding_sha"
}
verify_staged_release() {
  local image_id=$1 branding=$2 crm=$3 finance=$4 oa=${5:-} service running label
  for service in "${services[@]}"; do
    test "$(docker inspect "frappe_docker-$service-1" --format '{{.Image}}')" = "$image_id" || return 1
    label=$(revision_label "frappe_docker-$service-1" branding) || return 1
    test "$label" = "$branding" || return 1
    label=$(revision_label "frappe_docker-$service-1" crm) || return 1
    test "$label" = "$crm" || return 1
    label=$(revision_label "frappe_docker-$service-1" finance) || return 1
    test "$label" = "$finance" || return 1
    label=$(revision_label "frappe_docker-$service-1" oa) || return 1
    test "$label" = "$oa" || return 1
    running=$(docker inspect "frappe_docker-$service-1" --format '{{.State.Running}}') || return 1
    test "$running" = false || return 1
  done
}
prepare_sources() {
  python3 - "$build_dir" "$archive" "$crm_archive" "$finance_archive" "${oa_archive:-}" "${budget_file:-}" <<'PY'
import hashlib
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1])
budget = json.loads(Path(sys.argv[6]).read_bytes()) if sys.argv[6] else None
if budget is not None:
    assert {str(Path(value).resolve()): hashlib.sha256(Path(value).read_bytes()).hexdigest() for value in sys.argv[2:6] if value} == budget['archives'], 'Archives changed after space budget'
finance_files = {'services/voucher.py', 'tests/test_cancellation_sync.py'}
oa_files = {'hooks.py', 'oa_purchase_request/oa_purchase_request.py'}
deploy_files = {'deploy/production/deploy_unified_purchase.sh', 'deploy/production/audit_unified_purchase.py',
		        'deploy/production/procurement_release_metadata.py',
                'deploy/production/joint_release_guards.py',
                'deploy/production/dedicated_source_sync.py',
                'deploy/production/main_site_lane.py',
                'deploy/production/systemd/deeplinkerp-source-sync.service',
                'deploy/production/systemd/deeplinkerp-source-sync.timer',
                'deploy/local/Dockerfile.unified-purchase'}
archives = []
manifest = None
overlaid = {'deeplinkerp_branding'}
for kind, archive in zip(('branding', 'crm', 'finance', 'oa'), sys.argv[2:6]):
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
                elif kind == 'finance':
                    assert any(path in PurePosixPath('finance-overlay/china_finance/' + file).parents for file in finance_files), 'Unexpected Finance archive directory'
                else:
                    assert any(path in PurePosixPath('oa-overlay/oa_purchase_request/' + file).parents for file in oa_files), 'Unexpected OA archive directory'
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
            elif kind == 'finance':
                assert member.name in {'finance-overlay/china_finance/' + path for path in finance_files}, 'Unexpected Finance archive file'
            else:
                assert member.name in {'oa-overlay/oa_purchase_request/' + path for path in oa_files}, 'Unexpected OA archive file'
        archives.append((archive, [member for member in members if member.name != 'release-source-manifest.json']))
        if kind != 'branding':
            overlaid.add({'crm': 'crm_integration', 'finance': 'china_finance', 'oa': 'oa_purchase_request'}[kind])
        if kind == 'finance':
            assert files_seen - {'release-source-manifest.json'} == {'finance-overlay/china_finance/' + path for path in finance_files}, 'Incomplete Finance overlay'
        if kind == 'oa':
            assert files_seen - {'release-source-manifest.json'} == {'oa-overlay/oa_purchase_request/' + path for path in oa_files}, 'Incomplete OA overlay'
if len(overlaid) > 1:
    assert manifest is not None, 'Optional app overlays require a release manifest'
if manifest is not None:
    assert set(manifest['apps']) == overlaid, 'Manifest app set differs from overlays'
    if 'china_finance' in overlaid:
        assert set(manifest['apps']['china_finance']) == finance_files, 'Unexpected Finance manifest files'
    if 'oa_purchase_request' in overlaid:
        assert set(manifest['apps']['oa_purchase_request']) == oa_files, 'Unexpected OA manifest files'
    for app, files in manifest['apps'].items():
        assert files, 'Empty app manifest'
        for name in files:
            path = PurePosixPath(name)
            assert name and not path.is_absolute() and '..' not in path.parts and '\\' not in name
            assert str(path) == name and path.parts, 'Invalid manifest path'
for archive, members in archives:
    with tarfile.open(archive, 'r:gz') as tar:
        tar.extractall(root, members=members)
for directory in ('crm-overlay', 'finance-overlay', 'oa-overlay'):
    (root / directory).mkdir(exist_ok=True)
if manifest is not None:
    for app, files in manifest['apps'].items():
        prefix = {'deeplinkerp_branding': 'deeplinkerp_branding', 'crm_integration': 'crm-overlay/crm_integration',
                  'china_finance': 'finance-overlay/china_finance', 'oa_purchase_request': 'oa-overlay/oa_purchase_request'}[app]
        for name, versions in files.items():
            candidate = root / prefix / name
            assert candidate.is_file(), f'Missing candidate source: {app}/{name}'
            assert hashlib.sha256(candidate.read_bytes()).hexdigest() == versions['after'], f'Candidate source drift: {app}/{name}'
    if 'release_tools' in manifest:
        assert set(manifest['release_tools']) == deploy_files, 'Incomplete/unapproved release tool set'
        for name, digest in manifest['release_tools'].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, 'Release tool drift: ' + name
    (root / 'release-source-manifest.json').write_text(json.dumps(manifest, sort_keys=True))
PY
}
approve_release_sources() {
  # Same full maps for the isolated main or the retained compatibility caller.
  python3 - "$release_dir" "$build_dir" <<'PY'
import copy,hashlib,json,sys
from pathlib import Path
evidence,build=map(Path,sys.argv[1:]);sys.path.insert(0,str(build/'deploy/production'))
from joint_release_guards import merge_frozen_branding_sources
manifest=json.loads((build/'release-source-manifest.json').read_bytes());pinned=json.loads((evidence/'pinned-base-sources.json').read_bytes())
root=build/'deeplinkerp_branding'
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}}
for baseline in (evidence/'before.json',*evidence.glob('*.before.json')):
 before=json.loads(baseline.read_bytes())
 assert before['release_sources_all']=={app:pinned[app] for app in before['release_sources_all']}, 'Dirty server app source differs from immutable base; HOLD'
 after=copy.deepcopy(before['release_sources_all']);after['deeplinkerp_branding']=merge_frozen_branding_sources(after['deeplinkerp_branding'],files)
 for app in ('china_finance','oa_purchase_request'):
  assert app in after, 'Required shared overlay package absent; no auto-install'
  for path,versions in manifest['apps'][app].items():
   assert before['release_sources_all'][app].get(path)==versions['before'], 'Unapproved app baseline'
   after[app][path]=versions['after']
 before['approved_sources_after']=after
 baseline.write_text(json.dumps(before,sort_keys=True,ensure_ascii=False))
PY
}
verify_audit_ownership() {
  python3 - "$release_dir" "$build_dir" "$branding_sha" "$new_image_id" "$old_image_id" "$main_only" <<'PY'
import hashlib,json,os,sys
from pathlib import Path
root,build=map(Path,sys.argv[1:3]);sys.path.insert(0,str(build/'deploy/production'))
from procurement_release_metadata import verify_joint_audit_delta
verify_joint_audit_delta(json.loads((root/'before.json').read_bytes()),json.loads((root/'after.json').read_bytes()),json.loads((root/'joint-receipt.json').read_bytes()))
sites=() if sys.argv[6]=='1' else ('akivision.deeplinkerp.com','latingo.deeplinkerp.com','yuewei.deeplinkerp.com')
for site in sites:
 verify_joint_audit_delta(json.loads((root/(site+'.before.json')).read_bytes()),json.loads((root/(site+'.after.json')).read_bytes()),json.loads((root/(site+'.joint-receipt.json')).read_bytes()))
stats=build.stat();files={str(p.relative_to(build)):hashlib.sha256(p.read_bytes()).hexdigest() for p in build.rglob('*') if p.is_file()}
owned={'path':str(build),'identity':[stats.st_dev,stats.st_ino,stats.st_uid],'candidate_sha':sys.argv[3],'image_id':sys.argv[4],'files':files,'max_bytes':sum(p.stat().st_size for p in build.rglob('*') if p.is_file()),'manifest_sha256':files['release-source-manifest.json'],'guard_sha256':files['deploy/production/joint_release_guards.py'],'raw_assets':{ '/assets/deeplinkerp_branding/js/inventory_detail.bundle.js?v=0.0.4':files['deeplinkerp_branding/public/js/inventory_detail.bundle.js'],'/assets/deeplinkerp_branding/js/purchase_payments.js?v=0.0.26':files['deeplinkerp_branding/public/js/purchase_payments.js']}}
owned['rollback_image_id']=sys.argv[5]
owned['directories']=sorted(str(p.relative_to(build)) for p in build.rglob('*') if p.is_dir())
if sys.argv[6]=='1':
 owned['lane']='main-only'
 owned['main_helper_sha256']=files['deploy/production/main_site_lane.py']
 state=json.loads((root/'main-seal.json').read_bytes())
 owned['old_containers']=state['before']['containers']
 owned['old_raw_assets']={url:json.loads((root/'before.json').read_bytes())['release_sources_all']['deeplinkerp_branding']['public/'+url.split('/assets/deeplinkerp_branding/',1)[1].split('?')[0]] for url in owned['raw_assets']}
(root/'build-ownership.json').write_text(json.dumps(owned,sort_keys=True))
print('Complete bounded metadata/business/source audit passed before first resume')
PY
}
main_lane() {
  local action=$1
  shift
  python3 "$build_dir/deploy/production/main_site_lane.py" "$action" \
    --evidence "$(pwd)/$release_dir" --build "$build_dir" "$@"
}
recover_main_only() {
  local code=$?
  (( code != 0 )) || return 0
  trap - EXIT
  if [[ ! -f "$release_dir/main-seal.json" ]]; then
    echo 'Main preflight failed before boundary changes; inspect the private evidence.' >&2
    exit "$code"
  fi
  if ! main_lane boundary-pre-resume > /dev/null; then
    if main_lane hold > "$release_dir/main-hold.json"; then
      echo 'Main first producer resume recorded/unknown: main maintenance HOLD; forward-only.' >&2
    else
      echo 'Main first producer resume recorded/unknown: HOLD UNCONFIRMED; forward-only. Inspect the private hold attempt.' >&2
    fi
    exit "$code"
  fi
  local recovery_ok=1
  if (( ${metadata_started:-0} )); then
    command_runner "$old_image_id" "$python" "$metadata" --joint-rollback --receipt "$native_receipt" --candidate-sha "$branding_sha" --source-phase before > "$release_dir/metadata-rollback.json" || recovery_ok=0
    if (( recovery_ok )); then
      capture_release_audit before "$release_dir/rollback.json" "$old_image_id" || recovery_ok=0
      python3 - "$release_dir" <<'PY' || recovery_ok=0
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);before=json.loads((root/'before.json').read_bytes());before.pop('approved_sources_after',None)
assert before==json.loads((root/'rollback.json').read_bytes()), 'Restored full main audit differs; maintenance HOLD'
PY
    fi
  fi
  if (( recovery_ok )); then main_lane restore > "$release_dir/main-boundary-restore.json" || recovery_ok=0; fi
  if (( recovery_ok && source_sync_timer_active )); then
    original_runner=$(python3 -c 'import json;print(json.load(open("/home/yuewei/.local/state/deeplinkerp-source-sync/config.json"))["runner_sha256"])') || recovery_ok=0
    if (( recovery_ok )); then
      flock -u 8; flock -u 9
      retarget_existing_source_sync "$old_image_id" "$current_revision" "$original_runner" frappe_docker-backend-1 || recovery_ok=0
    fi
  fi
  if (( ! recovery_ok )); then
    if main_lane hold > "$release_dir/main-hold.json"; then
      echo 'Main restore is unconfirmed; maintenance HOLD. Inspect durable intents.' >&2
    else
      echo 'Main restore and HOLD UNCONFIRMED. Inspect durable intents and the private hold attempt.' >&2
    fi
  fi
  exit "$code"
}
run_main_only_release() {
  command_runner "$new_image_id" "$python" "$guard" --tenant-preflight --main-only --erpnext-version "$expected_erpnext" > "$release_dir/tenants.json"
  metadata_started=0
  trap recover_main_only EXIT
  main_lane prepare --base-image "$old_image_id" --image-id "$new_image_id" --candidate-sha "$branding_sha" > "$release_dir/main-prepare.json"
  main_prepared=1
  capture_release_audit before "$release_dir/before.json" "$old_image_id"
  apps=$(python3 -c 'import json,sys;print(json.dumps(sorted(json.load(open(sys.argv[1]))["release_sources_all"])))' "$release_dir/before.json")
  capture_pinned_sources "$old_image_id" "$release_dir/pinned-base-sources.json" "$apps"
  approve_release_sources
  main_lane space > "$release_dir/main-space-before.json"
  command_runner "$new_image_id" "$python" -c 'import sys;from pathlib import Path;Path(sys.argv[1]).parent.mkdir(parents=True,exist_ok=True)' "$native_receipt"
  metadata_started=1
  command_runner "$new_image_id" "$python" "$metadata" --joint-apply --receipt "$native_receipt" --candidate-sha "$branding_sha" --before-audit /release-evidence/before.json > "$release_dir/metadata.json"
  command_runner "$new_image_id" "$python" -c 'import sys;from pathlib import Path;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())' "$native_receipt" > "$release_dir/joint-receipt.json"
  command_runner "$new_image_id" bench --site deeplinkerp.com clear-cache
  capture_release_audit after "$release_dir/after.json" "$new_image_id"
  verify_audit_ownership
  main_lane space > "$release_dir/main-space-after.json"
  # Bounded metadata is reversible; web/RQ/source producers are forward-only.
  command_runner "$new_image_id" "$python" "$guard" --record-resume --receipt "$resume_receipt" --candidate-sha "$branding_sha" --image-id "$new_image_id" --producer main-candidate-serving > "$release_dir/resume.json"
  main_lane resume > "$release_dir/main-resume.json"
  flock -u 8; flock -u 9
  retarget_existing_source_sync "$new_image_id"
  main_lane health > "$release_dir/main-health.json"
  trap - EXIT
  printf '\nMain cutover health verified; actual logged-in browser URL/body-SHA acceptance and owned-build cleanup remain required.\n'
}
cd /home/yuewei/ERPNext-Docker/frappe_docker
exec 9>/tmp/deeplinkerp-erp-release.lock
flock -n 9 || { echo 'Another ERP release or source job owns the lock'; exit 1; }
mkdir -p /home/yuewei/.local/state/deeplinkerp-source-sync
exec 8>/home/yuewei/.local/state/deeplinkerp-source-sync/run.lock
flock -n 8 || { echo 'Source host execution owns the lock'; exit 1; }
dc=(docker compose -p frappe_docker -f compose.custom.yaml)
"${dc[@]}" up --no-start --force-recreate --no-deps --help > /dev/null
services=(backend frontend queue-long queue-short scheduler websocket)
sites=(deeplinkerp.com akivision.deeplinkerp.com latingo.deeplinkerp.com yuewei.deeplinkerp.com)
release_key="${branding_sha:0:12}-finance-${finance_sha:0:12}-oa-${oa_sha:0:12}"
release_dir="private/release-evidence/unified-purchase-$release_key"
native_receipt="/home/frappe/frappe-bench/sites/deeplinkerp.com/private/release-evidence/joint-${branding_sha:0:12}.json"
resume_receipt="${native_receipt%.json}.resume.json"
mkdir -p private/release-evidence
mkdir "$release_dir" # Existing/unknown receipt means HOLD; never infer interrupted absence.
budget_file="$(pwd)/$release_dir/space-budget.json"
# Read the reviewed guard in memory. No extraction/build/backup precedes this budget.
python3 - "$archive" "$finance_archive" "$oa_archive" "$old_image_id" "$branding_sha" "$finance_sha" "$oa_sha" "$0" "$main_only" > "$budget_file" <<'PY'
import hashlib,json,sys,tarfile
from pathlib import Path
with tarfile.open(sys.argv[1], 'r:gz') as tar:
 manifest=json.load(tar.extractfile('release-source-manifest.json'))
 code=tar.extractfile('deploy/production/joint_release_guards.py').read()
assert manifest['release_tools']['deploy/production/joint_release_guards.py']==hashlib.sha256(code).hexdigest(), 'Unfrozen guard'
assert manifest['release_tools']['deploy/production/deploy_unified_purchase.sh']==hashlib.sha256(Path(sys.argv[8]).read_bytes()).hexdigest(), 'Entrypoint differs from frozen archive'
assert manifest['base_image_id']==sys.argv[4], 'Unapproved base image'
assert manifest['revisions']==dict(deeplinkerp_branding=sys.argv[5],china_finance=sys.argv[6],oa_purchase_request=sys.argv[7]), 'Unfrozen app revisions'
assert manifest['native_versions']['frappe']=='16.23.0' and manifest['native_versions'].get('erpnext'), 'Precise approved native versions required; not latest version-16'
scope={'__name__':'release_budget'}
exec(compile(code,'frozen-joint-release-guards','exec'),scope)
print(json.dumps(scope['release_space_budget'](sys.argv[1:4],sys.argv[4],main_only=sys.argv[9]=='1'),sort_keys=True))
PY
build_dir=$(mktemp -d /tmp/unified-purchase-build.XXXXXX)
prepare_sources
main_lane runtime-access > "$release_dir/private-access.json"
private_runtime_gid=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["private_gid"])' "$release_dir/private-access.json")
chmod -R a+rX "$build_dir" # Source only; private audit/backup files are separate.
cp "$build_dir/deploy/production/joint_release_guards.py" "$release_dir/joint_release_guards.py"
if (( main_only )); then cp "$build_dir/deploy/production/main_site_lane.py" "$release_dir/main_site_lane.py"; fi
python3 - "$release_dir" <<'PY'
import json,subprocess,sys
from pathlib import Path
backend=json.loads(subprocess.check_output(['docker','inspect','frappe_docker-backend-1']))[0]
sites=[item for item in backend['Mounts'] if item['Destination']=='/home/frappe/frappe-bench/sites']
assert len(sites)==1 and sites[0]['Type'] in {'bind','volume'}, 'Unknown shared sites mount'
Path(sys.argv[1],'runner-mount.json').write_text(json.dumps({'sites':sites[0].get('Name') if sites[0]['Type']=='volume' else sites[0]['Source'],'network':backend['HostConfig']['NetworkMode']}))
PY
sites_spec=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sites"])' "$release_dir/runner-mount.json")
release_network=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["network"])' "$release_dir/runner-mount.json")
python=/home/frappe/frappe-bench/env/bin/python
guard=/release/deploy/production/joint_release_guards.py
metadata=/release/deploy/production/procurement_release_metadata.py
audit_args=(--purchase-payment-page-source /release/deeplinkerp_branding/deeplinkerp_branding/page/purchase_payment_records/purchase_payment_records.json --joint-metadata --release-manifest /release/release-source-manifest.json)
expected_erpnext=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["native_versions"]["erpnext"])' "$build_dir/release-source-manifest.json")
current_revision=$(revision_label frappe_docker-backend-1 branding)
current_crm=$(revision_label frappe_docker-backend-1 crm)
current_finance=$(revision_label frappe_docker-backend-1 finance)
current_oa=$(revision_label frappe_docker-backend-1 oa)
crm_sha=$current_crm
source_sync_timer_active=0
source_sync_status=0
source_sync_state=$(systemctl --user is-active deeplinkerp-source-sync.timer) || source_sync_status=$?
case "$source_sync_state:$source_sync_status" in
  active:0) test -s /home/yuewei/.local/state/deeplinkerp-source-sync/config.json; source_sync_timer_active=1 ;;
  inactive:3) ;;
  unknown:4) test ! -e /home/yuewei/.local/state/deeplinkerp-source-sync/config.json ;;
  *) echo 'Existing source timer state is unconfirmed; HOLD.' >&2; exit 1 ;;
esac
if (( source_sync_timer_active )); then systemctl --user stop deeplinkerp-source-sync.timer; fi
python3 "$build_dir/deploy/production/joint_release_guards.py" --source-host-proof > "$release_dir/source-host.json"
if release_is_current; then
  current_image_id=$(docker inspect frappe_docker-backend-1 --format '{{.Image}}')
  capture_release_audit current "$release_dir/current-contract.json" "$current_image_id"
  for site in "${sites[@]:1}"; do
    capture_release_audit current "$release_dir/$site.current-contract.json" "$current_image_id" "$site"
  done
  apps=$(python3 -c 'import json,sys;print(json.dumps(sorted(json.load(open(sys.argv[1]))["release_sources_all"])))' "$release_dir/current-contract.json")
  capture_pinned_sources "$current_image_id" "$release_dir/current-image-sources.json" "$apps"
  python3 - "$release_dir" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);current=json.loads((root/'current-contract.json').read_bytes())
assert current['current_contract_verified'] and current['release_sources_all']==json.loads((root/'current-image-sources.json').read_bytes()), 'Current immutable source/native contract differs'
PY
  # Unknown historic serving without a durable first-resume marker is HOLD.
  command_runner "$current_image_id" "$python" -c 'from pathlib import Path;import json,sys;state=json.loads(Path(sys.argv[1]).read_bytes());assert state["identity"]["candidate_sha"]==sys.argv[2] and state["contract"]["image_id"]==sys.argv[3]' "$resume_receipt" "$branding_sha" "$current_image_id"
  flock -u 8
  flock -u 9
  retarget_existing_source_sync "$current_image_id"
  release_is_current
  echo 'Target revision already running; native contract verified, no repeated cutover.'
  exit 0
fi
verify_running_release "$old_image_id" "$current_revision" "$current_crm" "$current_finance" "$current_oa"
for service in "${services[@]}"; do
  test "$(docker inspect "frappe_docker-$service-1" --format '{{.Config.Image}}')" = "$old_image"
done
test "$(docker image inspect "$old_image" --format '{{.Id}}')" = "$old_image_id"
cp compose.custom.yaml "$release_dir/compose.before.yaml"
new_image="deeplinkerp-custom:unified-purchase-$release_key"
frozen_base="deeplinkerp-custom:unified-base-$release_key"
docker image tag "$old_image_id" "$frozen_base"
test "$(docker image inspect "$frozen_base" --format '{{.Id}}')" = "$old_image_id"
docker build --build-arg "BASE_IMAGE=$frozen_base" --build-arg "BASE_IMAGE_ID=$old_image_id" --build-arg "BRANDING_SHA=$branding_sha" --build-arg "CRM_SHA=$crm_sha" --build-arg "FINANCE_SHA=$finance_sha" --build-arg "OA_SHA=$oa_sha" \
  -f "$build_dir/deploy/local/Dockerfile.unified-purchase" -t "$new_image" "$build_dir"
new_image_id=$(docker image inspect "$new_image" --format '{{.Id}}')
for app in branding crm finance oa; do
  case "$app" in branding) expected=$branding_sha;; crm) expected=$crm_sha;; finance) expected=$finance_sha;; oa) expected=$oa_sha;; esac
  test "$(revision_label "$new_image_id" "$app")" = "$expected"
done
test "$(docker image inspect "$new_image_id" --format '{{index .Config.Labels "org.deeplinkerp.base.image"}}')" = "$old_image_id"
if (( main_only )); then run_main_only_release; exit; fi
# Candidate preflight is read-only and command-only. No app is installed/global-migrated.
command_runner "$new_image_id" "$python" "$guard" --tenant-preflight --erpnext-version "$expected_erpnext" > "$release_dir/tenants.json"
python3 - "$old_image" "$new_image" "$release_dir" "$frozen_base" <<'PY'
import sys
from pathlib import Path
source=Path('compose.custom.yaml').read_text()
assert source.count(sys.argv[1])==7, 'Unexpected Compose baseline; no dirty overwrite'
Path(sys.argv[3],'compose.after.yaml').write_text(source.replace(sys.argv[1],sys.argv[2]))
Path(sys.argv[3],'compose.rollback.yaml').write_text(source.replace(sys.argv[1],sys.argv[4]))
PY
maintenance=0
baseline_captured=0
metadata_started=0
metadata_started_sites=()
recover() {
  code=$?
  if (( code == 0 )); then return; fi
  trap - EXIT
  # BEFORE compose/image/schema changes. Present OR unreadable intent is forward-only.
  if ! command_runner "$old_image_id" "$python" "$guard" --assert-pre-resume --receipt "$resume_receipt" > /dev/null; then
    command_runner "$new_image_id" "$python" "$guard" --maintenance-on --tenant-receipt /release-evidence/tenants.json || true
    echo 'First resume/unknown receipt: maintenance HOLD, forward-only. No image/schema/business rollback.' >&2
    exit "$code"
  fi
  recovery_ok=1
  # Never re-quiesce or issue a second signal. A failed/partial drain stays HOLD.
  if (( ! baseline_captured || ! metadata_started )); then recovery_ok=0; fi
  for service in "${services[@]}"; do
    test "$(docker inspect "frappe_docker-$service-1" --format '{{.State.Running}}')" = false || recovery_ok=0
  done
  if (( recovery_ok )); then
    for ((i=${#metadata_started_sites[@]}-1; i>=0; i--)); do
      site=${metadata_started_sites[$i]}
      site_receipt="/home/frappe/frappe-bench/sites/$site/private/release-evidence/joint-${branding_sha:0:12}.json"
      command_runner "$old_image_id" "$python" "$metadata" --joint-rollback --site "$site" --native-only --receipt "$site_receipt" --candidate-sha "$branding_sha" --source-phase before > "$release_dir/$site.metadata-rollback.json" || recovery_ok=0
    done
    command_runner "$old_image_id" "$python" "$metadata" --joint-rollback --receipt "$native_receipt" --candidate-sha "$branding_sha" --source-phase before > "$release_dir/metadata-rollback.json" || recovery_ok=0
    capture_release_audit before "$release_dir/rollback.json" "$old_image_id" || recovery_ok=0
    for site in "${sites[@]:1}"; do
      capture_release_audit before "$release_dir/$site.rollback.json" "$old_image_id" "$site" || recovery_ok=0
    done
  fi
  if (( recovery_ok )); then
    python3 - "$release_dir" <<'PY' || recovery_ok=0
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);before=json.loads((root/'before.json').read_bytes());before.pop('approved_sources_after',None)
assert before==json.loads((root/'rollback.json').read_bytes()), 'Restored full audit differs; maintenance retained'
for site in ('akivision.deeplinkerp.com','latingo.deeplinkerp.com','yuewei.deeplinkerp.com'):
 old=json.loads((root/(site+'.before.json')).read_bytes());old.pop('approved_sources_after',None)
 restored=root/(site+'.rollback.json')
 assert restored.exists() and old==json.loads(restored.read_bytes()), 'Shared-site original audit not proved: '+site
print('Restored full audit matches original baseline')
PY
  fi
  if (( recovery_ok )); then
    test "$(docker image inspect "$frozen_base" --format '{{.Id}}')" = "$old_image_id" || recovery_ok=0
    cp "$release_dir/compose.rollback.yaml" compose.custom.yaml || recovery_ok=0
    "${dc[@]}" up --no-start --force-recreate --no-deps backend frontend queue-long queue-short scheduler websocket || recovery_ok=0
    verify_staged_release "$old_image_id" "$current_revision" "$current_crm" "$current_finance" "$current_oa" || recovery_ok=0
  fi
  if (( recovery_ok )); then
    command_runner "$old_image_id" "$python" "$guard" --record-resume --receipt "$resume_receipt" --candidate-sha "$branding_sha" --image-id "$old_image_id" --producer old-serving > "$release_dir/resume.json" || recovery_ok=0
    if (( recovery_ok )); then
      "${dc[@]}" up -d --no-deps "${services[@]}" || recovery_ok=0
      verify_running_release "$old_image_id" "$current_revision" "$current_crm" "$current_finance" "$current_oa" || recovery_ok=0
      command_runner "$old_image_id" "$python" "$guard" --maintenance-restore --tenant-receipt /release-evidence/tenants.json || recovery_ok=0
      for site in "${sites[@]}"; do curl -fsS --max-time 10 "https://$site/api/method/ping" || recovery_ok=0; done
    fi
  fi
  if (( recovery_ok && ${source_sync_timer_active:-0} )); then
    original_runner=$(python3 -c 'import json;print(json.load(open("/home/yuewei/.local/state/deeplinkerp-source-sync/config.json"))["runner_sha256"])') || recovery_ok=0
    if (( recovery_ok )); then
      flock -u 8
      flock -u 9
      retarget_existing_source_sync "$old_image_id" "$current_revision" "$original_runner" || recovery_ok=0
    fi
  fi
  if (( ! recovery_ok )); then
    command_runner "$old_image_id" "$python" "$guard" --maintenance-on --tenant-receipt /release-evidence/tenants.json || true
    echo 'Rollback/drain cannot be verified; maintenance HOLD. Manual forward inspection required.' >&2
  fi
  exit "$code"
}
trap recover EXIT
command_runner "$new_image_id" "$python" "$guard" --maintenance-on --tenant-receipt /release-evidence/tenants.json
maintenance=1
# Copy only reviewed read-only diagnostic code, never installed app/server source.
chmod 644 "$build_dir/deploy/production/joint_release_guards.py"
for service in backend queue-long queue-short scheduler websocket; do
  docker cp "$build_dir/deploy/production/joint_release_guards.py" "frappe_docker-$service-1:/tmp/joint_release_guards.py"
done
quiesce_release_workers
command_runner "$old_image_id" bench --site deeplinkerp.com backup --with-files --compress > "$release_dir/backup.log"
capture_release_audit before "$release_dir/before.json" "$old_image_id"
for site in "${sites[@]:1}"; do
  capture_release_audit before "$release_dir/$site.before.json" "$old_image_id" "$site"
done
baseline_captured=1
apps=$(python3 -c 'import json,sys;from pathlib import Path;root=Path(sys.argv[1]);paths=[root/"before.json",*root.glob("*.before.json")];print(json.dumps(sorted(set().union(*(json.loads(p.read_bytes())["release_sources_all"] for p in paths)))))' "$release_dir")
capture_pinned_sources "$old_image_id" "$release_dir/pinned-base-sources.json" "$apps"
approve_release_sources
# All six containers are staged stopped. Metadata and the complete audit precede ANY serving startup.
cp "$release_dir/compose.after.yaml" compose.custom.yaml
"${dc[@]}" config --quiet
"${dc[@]}" up --no-start --force-recreate --no-deps backend frontend queue-long queue-short scheduler websocket
verify_staged_release "$new_image_id" "$branding_sha" "$crm_sha" "$finance_sha" "$oa_sha"
command_runner "$new_image_id" "$python" -c 'import sys;from pathlib import Path;Path(sys.argv[1]).parent.mkdir(parents=True,exist_ok=True)' "$native_receipt"
metadata_started=1
command_runner "$new_image_id" "$python" "$metadata" --joint-apply --receipt "$native_receipt" --candidate-sha "$branding_sha" --before-audit /release-evidence/before.json > "$release_dir/metadata.json"
command_runner "$new_image_id" "$python" -c 'import sys;from pathlib import Path;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())' "$native_receipt" > "$release_dir/joint-receipt.json"
for site in "${sites[@]:1}"; do
  site_receipt="/home/frappe/frappe-bench/sites/$site/private/release-evidence/joint-${branding_sha:0:12}.json"
  command_runner "$new_image_id" "$python" -c 'import sys;from pathlib import Path;Path(sys.argv[1]).parent.mkdir(parents=True,exist_ok=True)' "$site_receipt"
  metadata_started_sites+=("$site")
  command_runner "$new_image_id" "$python" "$metadata" --joint-apply --site "$site" --native-only --receipt "$site_receipt" --candidate-sha "$branding_sha" --before-audit "/release-evidence/$site.before.json" > "$release_dir/$site.metadata.json"
  command_runner "$new_image_id" "$python" -c 'import sys;from pathlib import Path;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())' "$site_receipt" > "$release_dir/$site.joint-receipt.json"
done
# Existing compiled inventory bundles/maps are preserved, NOT claimed rebuilt.
command_runner "$new_image_id" /usr/bin/touch /home/frappe/frappe-bench/sites/assets/assets.json
for site in "${sites[@]}"; do command_runner "$new_image_id" bench --site "$site" clear-cache; done
capture_release_audit after "$release_dir/after.json" "$new_image_id"
for site in "${sites[@]:1}"; do
  capture_release_audit after "$release_dir/$site.after.json" "$new_image_id" "$site"
done
verify_audit_ownership
command_runner "$new_image_id" "$python" "$guard" --record-resume --receipt "$resume_receipt" --candidate-sha "$branding_sha" --image-id "$new_image_id" --producer candidate-serving > "$release_dir/resume.json"
"${dc[@]}" up -d --no-deps "${services[@]}"
verify_running_release "$new_image_id" "$branding_sha" "$crm_sha" "$finance_sha" "$oa_sha"
command_runner "$new_image_id" "$python" "$guard" --maintenance-restore --tenant-receipt /release-evidence/tenants.json
for site in "${sites[@]}"; do curl -fsS --max-time 10 "https://$site/api/method/ping"; done
command_runner "$new_image_id" "$python" -c 'import json,sys;from pathlib import Path;actual=json.loads(Path(sys.argv[1]).read_bytes());expected=json.loads(Path("/release-evidence/resume.json").read_bytes());assert actual==expected and actual["contract"]["first_resume"]=="candidate-serving"' "$resume_receipt"
# Cutover is verified; first web/RQ resume already wrote a durable forward-only intent.
flock -u 8
flock -u 9
retarget_existing_source_sync "$new_image_id"
release_is_current
trap - EXIT
docker inspect frappe_docker-backend-1 --format '{{.Config.Image}} {{.Image}}'
printf '\nApp cutover verified; actual logged-in browser URL/body-SHA acceptance and bounded owned-cache cleanup still required.\n'
