#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backup_dir="${WEAVE_BACKUP_DIR:-$root_dir/backups}"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_dir/weave-$stamp.dump"
cd "$root_dir"
docker compose -f docker-compose.yml exec -T postgres \
  pg_dump --format=custom --no-owner --no-acl --username=weave weave > "$target"
chmod 600 "$target"
sha256sum "$target" > "$target.sha256"
echo "$target"
