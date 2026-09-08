#!/usr/bin/env bash
set -euo pipefail

compose_root="${1:-/home/yuewei/ERPNext-Docker/frappe_docker}"
site_name="${2:-deeplinkerp.com}"
key_file="${3:?DeepSeek key file is required}"
compose_file="$compose_root/compose.custom.yaml"

cleanup_key() {
  if command -v shred >/dev/null 2>&1; then
    shred -u "$key_file" 2>/dev/null || rm -f "$key_file"
  else
    rm -f "$key_file"
  fi
}
trap cleanup_key EXIT

test -s "$key_file"
cd "$compose_root"
cat "$key_file" | docker compose -f "$compose_file" exec -T \
  -e "OCW_SITE_NAME=$site_name" \
  -w /home/frappe/frappe-bench \
  backend /home/frappe/frappe-bench/env/bin/python -c '
import json
import os
import pathlib
import sys
import tempfile

site = os.environ["OCW_SITE_NAME"]
config_path = pathlib.Path("/home/frappe/frappe-bench/sites") / site / "site_config.json"
api_key = sys.stdin.read().strip()
if not api_key:
    raise SystemExit("DeepSeek key is empty")
with config_path.open(encoding="utf-8") as handle:
    config = json.load(handle)
config["overseas_cost_ai_api_key"] = api_key
fd, temporary = tempfile.mkstemp(prefix="site_config.", suffix=".json", dir=str(config_path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(temporary, 0o640)
    os.replace(temporary, config_path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
'
docker compose -f "$compose_file" restart backend queue-short queue-long scheduler >/dev/null
# The runtime install recreates backend and can change its container IP. Nginx
# resolves the upstream when it starts, so reload it after backend is available.
docker compose -f "$compose_file" restart frontend >/dev/null
