#!/usr/bin/env bash
# Reclaim host disk before the image rebuild without deleting the image compose needs.
#
# `docker image prune --all` removes every image that no container references. When
# compose has just been repinned to a new tag and the containers have not been
# recreated yet, the image compose is about to use is referenced by nothing except
# the compose file itself, so the prune deleted it and the document-runtime preflight
# that runs right after died on docker's opaque "No such image" (hit for real on
# 2026-09-28). A stopped placeholder container pins that image for the duration of
# the prune and is deleted straight afterwards, so the reclaim stays as aggressive as
# before for everything else.
set -euo pipefail

compose_root="${1:?compose root is required}"
compose_file="$compose_root/compose.custom.yaml"
guard_container="ocw-deploy-image-guard"

base_image_script="${BASE_IMAGE_SCRIPT:-}"
if [ -z "$base_image_script" ] && [ -f "$(dirname "$0")/resolve_base_image.sh" ]; then
  base_image_script="$(dirname "$0")/resolve_base_image.sh"
fi

base_image=""
if [ -n "$base_image_script" ] && [ -f "$base_image_script" ]; then
  # shellcheck source=resolve_base_image.sh
  . "$base_image_script"
  base_image="$(resolve_base_image "$compose_file" 2>/dev/null || true)"
fi

docker rm --force "$guard_container" >/dev/null 2>&1 || true
guarded=0
if [ -n "$base_image" ] && docker image inspect "$base_image" >/dev/null 2>&1; then
  if docker create --name "$guard_container" "$base_image" >/dev/null; then
    guarded=1
  fi
fi

remove_guard() {
  if [ "$guarded" = "1" ]; then
    docker rm --force "$guard_container" >/dev/null 2>&1 || true
  fi
}
trap remove_guard EXIT

docker builder prune --all --force

if [ -n "$base_image" ]; then
  # The declared tag is known. Even when it is missing locally, `--all` cannot take
  # it away; the running containers keep whatever image they are actually on.
  if [ "$guarded" = "1" ]; then
    echo "Keeping $base_image alive across the prune: it is the image $compose_file declares."
  fi
  docker image prune --all --force
else
  # The compose file does not name a runtime image, so which tagged image is still
  # needed is unknown and a wrong `--all` here would break the next step. Only
  # dangling layers are reclaimed until the compose file is readable again.
  echo "Cannot resolve the image declared by $compose_file; reclaiming dangling layers only."
  docker image prune --force
fi

remove_guard
trap - EXIT
