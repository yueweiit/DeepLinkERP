#!/bin/sh
set -eu

dump=/backups/phone-scraper.dump
if [ ! -s "$dump" ]; then
  echo "phone-watch dump is missing or empty: $dump" >&2
  exit 1
fi

pg_restore \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --no-owner \
  --no-acl \
  --exit-on-error \
  "$dump"
