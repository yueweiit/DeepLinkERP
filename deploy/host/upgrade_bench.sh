#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="compose.custom.yaml"

IMAGE="deeplinkerp-custom:v16.23.0-latest"
IMAGE_LABEL="com.deeplinkerp.project=deeplinkerp"


echo "== 1. Validate apps.json =="

python3 -m json.tool apps.json >/dev/null


echo "== 2. Build custom image =="

docker build \
  --no-cache \
  --label="$IMAGE_LABEL" \
  --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
  --build-arg=FRAPPE_BRANCH=v16.23.0 \
  --secret=id=apps_json,src=apps.json \
  --tag="$IMAGE" \
  --file=images/layered/Containerfile \
  .


echo "== 3. Check image =="

docker image inspect "$IMAGE" \
  --format 'Image ID: {{.Id}}
Created: {{.Created}}
Labels: {{json .Config.Labels}}'


echo "== 4. Check apps in image =="

docker run --rm "$IMAGE" \
  ls -1 /home/frappe/frappe-bench/apps



echo "== 5. Backup compose =="

cp "$COMPOSE_FILE" \
"${COMPOSE_FILE}.bak.$(date +%F-%H%M)" || true


ls -1t "${COMPOSE_FILE}".bak.* 2>/dev/null \
| tail -n +3 \
| xargs -r rm -f



echo "== 6. Recreate containers =="

docker compose \
-f "$COMPOSE_FILE" \
up -d --force-recreate --wait


echo "== 7. Verify baked frontend assets =="

docker compose -f "$COMPOSE_FILE" exec -T frontend bash -lc '
set -e
cd /home/frappe/frappe-bench

test -s sites/assets/assets.json

find -L sites/assets/frappe/dist/css \
  -name "desk.bundle*.css" \
  -print -quit | grep -q .

find -L sites/assets/frappe/dist/js \
  -name "desk.bundle*.js" \
  -print -quit | grep -q .

echo "Frontend assets OK"
'

echo "== 8. Verify frontend assets =="

docker compose -f "$COMPOSE_FILE" exec -T frontend bash -lc '
set -e

cd /home/frappe/frappe-bench

test -s sites/assets/assets.json

find -L sites/assets/frappe/dist/css \
  -name "desk.bundle*.css" \
  -print -quit | grep -q .

find -L sites/assets/frappe/dist/js \
  -name "desk.bundle*.js" \
  -print -quit | grep -q .

echo "Frontend assets OK"
'


echo "== 10. Verify frontend can see assets =="

docker compose -f "$COMPOSE_FILE" exec -T frontend bash -lc '

cd /home/frappe/frappe-bench

ls -lh sites/assets/assets.json

find sites/assets -name "desk.bundle*.css" | head

find sites/assets -name "desk.bundle*.js" | head

'



echo "== 11. Restart services =="

docker compose -f "$COMPOSE_FILE" restart \
frontend \
backend \
websocket \
queue-short \
queue-long \
scheduler



echo "== 12. Verify running containers =="

docker compose -f "$COMPOSE_FILE" ps



echo "== 13. Remove dangling DeeplinkERP images =="

docker image prune -f \
--filter "label=$IMAGE_LABEL"



echo "== 14. Docker disk usage =="

docker system df


echo "== Done. Bench upgrade finished =="
echo "Run migrate_site.sh for each site"


