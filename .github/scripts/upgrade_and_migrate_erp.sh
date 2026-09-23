#!/usr/bin/env bash
set -euo pipefail

compose_root="${1:?compose root is required}"
site_name="${2:?site name is required}"

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
docker compose -f "$compose_root/compose.custom.yaml" exec -T -w /home/frappe/frappe-bench backend \
  bench --site "$site_name" execute overseas_costing.install.before_migrate
./migrate_site.sh "$site_name"
