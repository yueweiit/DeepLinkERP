#!/usr/bin/env bash
set -euo pipefail

compose_root="${1:?compose root is required}"
site_name="${2:?site name is required}"
required_inventory_branding_content_sha256="${3:?required inventory branding content sha256 is required}"

cd "$compose_root"

# The deploy host reuses a frappe_docker clone as the deployment scaffold and
# fast-forwards it on every release.  When upstream touches a file that also has
# uncommitted local edits, `git pull` refuses the merge ("Your local changes to
# the following files would be overwritten") and dies with exit code 1, which
# aborts the whole deployment before anything is upgraded.  That is exactly how
# the 2026-09-23 release stopped on overrides/compose.noproxy.yaml, after
# upstream 51a2740 changed the same file the host had edited locally.
#
# Strategy: fast-forward as usual and step in only when it is refused.  Take a
# durable backup of the local edits first, then realign the *tracked* files and
# retry.  Untracked files are never touched, so host-owned files such as
# compose.custom.yaml survive untouched.
if ! git pull --ff-only; then
  backup_dir="${LOCAL_CHANGE_BACKUP_DIR:-$(dirname "$compose_root")/local-change-backups}"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)-${GITHUB_RUN_ID:-local}"
  mkdir -p "$backup_dir"
  git status --porcelain > "$backup_dir/status-$stamp.txt"
  git diff > "$backup_dir/tracked-$stamp.patch"

  echo "Fast-forward was refused; the local edits are backed up to:"
  echo "  $backup_dir/status-$stamp.txt"
  echo "  $backup_dir/tracked-$stamp.patch"
  echo "Dirty tracked files: $(git diff --name-only | tr '\n' ' ')"
  echo "::warning::frappe_docker carried uncommitted local edits, so the fast-forward was refused. They were backed up and the tracked files realigned before retrying."

  git checkout -- .
  git pull --ff-only
fi

./upgrade_bench.sh

echo "== Verify paired inventory ownership before migrate =="
docker compose -f "$compose_root/compose.custom.yaml" exec -T \
  -e REQUIRED_INVENTORY_BRANDING_CONTENT_SHA256="$required_inventory_branding_content_sha256" \
  -w /home/frappe/frappe-bench backend python - <<'PY'
import hashlib
import os
from pathlib import Path

bench = Path("/home/frappe/frappe-bench")
branding_app = bench / "apps/deeplinkerp_branding"
overseas_app = bench / "apps/overseas_costing"
files = {
    Path("deeplinkerp_branding/hooks.py"),
    Path("deeplinkerp_branding/inventory_install.py"),
    Path("deeplinkerp_branding/services/inventory_detail_service.py"),
    Path("deeplinkerp_branding/public/js/inventory_detail.bundle.js"),
    Path("deeplinkerp_branding/public/css/inventory_detail.bundle.css"),
    Path(
        "deeplinkerp_branding/deeplinkerp_branding/doctype/"
        "inventory_original_location_snapshot/inventory_original_location_snapshot.json"
    ),
}
for directory in (
    Path("deeplinkerp_branding/deeplinkerp_branding/page/inventory_location_detail"),
    Path("deeplinkerp_branding/deeplinkerp_branding/page/semi_finished_inventory_detail"),
    Path("deeplinkerp_branding/deeplinkerp_branding/page/finished_goods_inventory_detail"),
    Path("deeplinkerp_branding/deeplinkerp_branding/page/mold_inventory_detail"),
    Path("deeplinkerp_branding/deeplinkerp_branding/doctype/inventory_original_location_snapshot"),
):
    full_directory = branding_app / directory
    if not full_directory.is_dir():
        raise SystemExit(f"inventory branding directory is missing: {directory}")
    files.update(
        path.relative_to(branding_app)
        for path in full_directory.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )

digest = hashlib.sha256()
for relative in sorted(files, key=lambda value: value.as_posix()):
    path = branding_app / relative
    if not path.is_file():
        raise SystemExit(f"inventory branding file is missing: {relative}")
    digest.update(relative.as_posix().encode())
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")

actual = digest.hexdigest()
expected = os.environ["REQUIRED_INVENTORY_BRANDING_CONTENT_SHA256"]
if actual != expected:
    raise SystemExit(
        f"inventory branding content digest mismatch: expected {expected}, got {actual}"
    )

for legacy_path in (
    Path("overseas_costing/services/inventory_location_service.py"),
    Path("overseas_costing/overseas_costing/page/inventory_location_detail"),
    Path("overseas_costing/overseas_costing/doctype/inventory_original_location_snapshot"),
):
    if (overseas_app / legacy_path).exists():
        raise SystemExit(f"legacy inventory owner still exists: {legacy_path}")

print(f"Inventory ownership content OK: {actual}")
PY

docker compose -f "$compose_root/compose.custom.yaml" exec -T -w /home/frappe/frappe-bench backend \
  bench --site "$site_name" execute overseas_costing.install.before_migrate
./migrate_site.sh "$site_name"
