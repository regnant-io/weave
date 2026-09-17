# Deploying Weave

This repository has a local developer stack, a temporary ngrok evaluation path,
and a production overlay. Keep them separate because
`docker-compose.override.yml` mounts the host Docker socket and enables
model-driven developer workspaces.

## Local development

```bash
docker compose --profile deep up --build
```

Compose loads the development override automatically. The frontend is at
`http://localhost:3000` and the API is at `http://localhost:8001`.

## Server evaluation deployment

The Kamatera helper creates fresh application and Postgres secrets, writes them
to `/opt/weave/.env` with mode `0600`, disables analysis and developer workspace
execution, and starts only the base Compose file.

```bash
export NGROK_AUTHTOKEN='value-from-your-secret-manager'
bash deploy-kamatera.sh
```

The ngrok tunnel exposes the frontend. Ordinary HTTP features work through the
Next.js server-side API routes. Live voice and collaborative canvas sockets need
the production reverse-proxy setup below; a browser outside the server cannot
reach the loopback-only backend port directly.

Inspect the deployment with explicit base-file commands so the development
override is never loaded:

```bash
cd /opt/weave
sudo docker-compose -f docker-compose.yml ps
sudo docker-compose -f docker-compose.yml logs -f backend frontend
curl -fsS http://127.0.0.1:8001/health
```

Create the first administrator through the interactive operator command. It
does not print or store the password outside the database hash:

```bash
sudo docker-compose -f docker-compose.yml exec backend \
  python -m app.cli create-admin --phone '+255700000000' --email 'admin@example.com'
```

Password registration creates an anonymous capability tier until SMS OTP is
verified. Configure Africa's Talking before opening self-service signup in
production; an unconfigured deployed SMS route returns 503 without logging OTPs.

## Production topology

The production overlay includes Caddy and routes one TLS origin to both services:

```bash
export WEAVE_DOMAIN=weave.example.org
export WEAVE_SECRET_KEY="$(openssl rand -hex 32)"
export POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export WEAVE_CORS_ORIGINS='["https://weave.example.org"]'
export WEAVE_S3_BUCKET=weave-production
# Set the S3 endpoint/region/access credentials required by your provider.
docker compose -f docker-compose.yml -f docker-compose.production.yml \
  --profile full up -d --build
```

The `full` profile is required: it starts the Celery owner for durable turns,
profiling, ingestion, crawling, and channel delivery. Do not add the `deep`
profile by default. Its browser and voice services remain development/evaluation
components until their images and egress boundaries pass the production gates.

Caddy then:

- Route normal traffic to frontend port `3000`.
- Route the complete `/api/v1/` surface, including WebSocket upgrades, to backend
  port `8001`.
- Sets the public WebSocket origin to `wss://$WEAVE_DOMAIN`.
- Keep backend, Postgres, Redis, render, Browserless, SearXNG, MinIO, Qdrant,
  ClickHouse, and Gotenberg ports bound to loopback or a private container network.
- Set `WEAVE_ENVIRONMENT=production`, `WEAVE_DEBUG=false`, a random
  `WEAVE_SECRET_KEY`, a random Postgres password, and the exact public origin in
  `WEAVE_CORS_ORIGINS`.

Production startup deliberately fails if the public demo account exists, the
development signing secret is used, model-written subprocess analysis is
enabled, or developer workspaces are enabled without an explicit override.
These checks prevent a development convenience from silently becoming a remote
execution path.

The API implements a signed remote analysis-runner client, but no runner is
shipped here. Keep analysis disabled until an isolated runner passes the hostile
fixtures in `ROADMAP.md`. Developer workspaces likewise need a separate host.

## Database migrations

New databases need no manual schema command: the deployed backend runs
`alembic upgrade head` before starting. A failed migration prevents the API from
starting, and production startup independently checks that the database revision
equals the repository head.

For a production Postgres database created by an older Weave version that has
tables but no `alembic_version` table:

1. Stop API and worker writes and create a verified backup.
2. Compare the existing schema with migration `a9583a2c2007`; fix any difference.
3. Mark only that known baseline, then apply later changes:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml run --rm backend \
  alembic stamp a9583a2c2007
docker compose -f docker-compose.yml -f docker-compose.production.yml run --rm backend \
  alembic upgrade head
```

Never stamp an uninspected database. `stamp` records a version without executing
schema changes.

## Backups and upgrades

Create and verify a database backup before every upgrade:

```bash
cd /opt/weave
sudo scripts/backup-postgres.sh
sudo scripts/verify-postgres-backup.sh backups/weave-TIMESTAMP.dump
git pull --ff-only
sudo docker compose -f docker-compose.yml -f docker-compose.production.yml build
sudo docker compose -f docker-compose.yml -f docker-compose.production.yml \
  --profile full up -d
```

On a Windows host with PowerShell 7.4 or newer, use the byte-safe equivalents:

```powershell
$backup = scripts/backup-postgres.ps1
scripts/verify-postgres-backup.ps1 $backup
```

When upgrading a named `backend_var` volume created by an older root-running
image, migrate its ownership once before starting the new API and worker:

```bash
docker compose run --rm --no-deps --user root --entrypoint chown backend -R 10001:10001 /app/var
```

Do not use `docker compose down -v` during normal operations; it deletes named
database and artifact volumes. Record the backup checksum, restore result,
deployed Git revision, and migration revision with every promotion.

After deployment, run the bilingual evaluation and Postgres retrieval benchmark:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml exec backend \
  python -m eval.run_eval
docker compose -f docker-compose.yml -f docker-compose.production.yml exec backend \
  python -m eval.benchmark_retrieval --min-recall 0.75 --max-p95-ms 250
```

Exercise storage and the public WebSocket path before promotion:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml \
  cp scripts/check-s3-contract.py backend:/tmp/check-s3-contract.py
docker compose -f docker-compose.yml -f docker-compose.production.yml exec backend \
  python /tmp/check-s3-contract.py
python scripts/check-production-websocket.py --origin "https://$WEAVE_DOMAIN"
python scripts/check-stream-resume.py --origin "https://$WEAVE_DOMAIN"
```

The WebSocket check creates and deletes its own user project. Run it with a unique
phone number if the target preserves users between drills.

## Secret incident

An ngrok credential was previously committed in deployment documentation and
scripts. The working tree no longer contains it, but Git history still does.
Revoke that credential in ngrok, create a replacement, and purge the old value
from shared Git history in a coordinated maintenance window.
