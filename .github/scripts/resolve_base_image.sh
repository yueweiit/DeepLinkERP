#!/usr/bin/env bash
# Resolve the custom base image tag from the compose file that production runs.
#
# The deploy chain relies on retagging this image onto the freshly built runtime
# image (`docker image tag "$runtime_image" "$base_image"`), so the name has to be
# whatever compose actually references. Hardcoding it meant a routine image bump
# on the server would silently break every later deploy, and a rename that did not
# touch the compose file would leave `docker compose up` recreating containers from
# the stale image. Reading it here keeps compose the single source of truth.

resolve_base_image() {
  local compose_file="${1:?compose file is required}"
  local image

  [ -f "$compose_file" ] || {
    echo "Compose file not found: $compose_file" >&2
    return 2
  }

  image="$(sed -nE 's/^[[:space:]]*image:[[:space:]]*(deeplinkerp-custom:[^[:space:]]+)[[:space:]]*$/\1/p' \
    "$compose_file" | head -1)"

  if [ -z "$image" ]; then
    echo "No deeplinkerp-custom image declared in $compose_file" >&2
    return 2
  fi

  printf '%s' "$image"
}
