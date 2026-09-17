#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 backups/weave-TIMESTAMP.dump" >&2
  exit 2
fi

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backup_file="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
test_db="weave_restore_$(date -u +%Y%m%d%H%M%S)_$$"

cleanup() {
  cd "$root_dir"
  docker compose -f docker-compose.yml exec -T postgres \
    dropdb --if-exists --force --username=weave "$test_db" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$root_dir"
sha256sum --check "$backup_file.sha256"
docker compose -f docker-compose.yml exec -T postgres \
  createdb --username=weave "$test_db"
docker compose -f docker-compose.yml exec -T postgres \
  pg_restore --exit-on-error --no-owner --no-acl --username=weave \
  --dbname="$test_db" < "$backup_file"
docker compose -f docker-compose.yml exec -T postgres \
  psql --username=weave --dbname="$test_db" --tuples-only --command \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
echo "restore verification passed: $backup_file"
