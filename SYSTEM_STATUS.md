# Weave system status

Last audited: 2026-09-14.

## Verified in this workspace

- Backend tests, authorization regressions, and clean Alembic upgrade/downgrade pass.
- Frontend ESLint, TypeScript, Next.js production build, and Playwright desktop/
  Pixel 7 auth, route-gate, upload, admin-denial, logout, multi-chat, repaired
  artifact, and hydration journeys pass without external font access.
- Render-service limit and contract tests plus its browser bundle build pass.
- The 20-case bilingual orchestration evaluation passes. The eight-query live
  Postgres pgvector benchmark records 100% recall@6, 9.0 ms p50, and 117.3 ms p95.
- Frontend/render npm audits and the pinned Python dependency audit report no known
  production vulnerabilities. Bandit has no high-severity result.
- Secret scanning, production image digest enforcement, shell syntax, SBOM jobs,
  static Compose/YAML checks, and the pinned runtime Trivy gate pass. Backend,
  frontend, and renderer images have zero fixable high/critical findings.
- A clean production-shaped Docker stack passed migrations, pgvector index checks,
  backup/restore, MinIO storage, Celery execution, Redis replay across API restart,
  readiness, and an HTTPS/WSS browser-protocol journey through Caddy.
- The repeatable stream-disconnect drill resumed 109 exact-cursor events without a
  gap or duplicate through the live Redis/Celery stack.

## Implemented production paths

- Alembic migrations, Postgres pgvector/HNSW plus full-text GIN, Redis-backed live
  turns and rate limits, Celery jobs with retry/dead-letter state, durable upload
  idempotency, webhook dedupe, transactional outbox, and S3-compatible storage.
- Fifteen-minute access tokens, rotating refresh-token families, server logout,
  single-use admin invitations, explicit admin authorization, and fail-closed channel
  verification.
- One-origin Caddy TLS/WebSocket routing, Postgres backup/restore scripts, bounded
  rendering/PDF/crawling, expiring artifact capabilities, and a signed remote
  analysis-runner client contract.

## Deployment gates

- Deploy and attack-test the isolated analysis runner. Deploy developer workspaces
  on a separate host before enabling either production execution capability.
- Repeat the local restore and public TLS/WebSocket evidence on the target staging
  origin; execute the Redis/Celery worker-loss drill and provider S3 lifecycle check.
- Run the retrieval benchmark on representative Postgres content and renderer/PDF
  load tests under container resource limits.
- Revoke the historical ngrok credential and coordinate Git-history cleanup.
- Apply registry admission scanning to promoted images; optional deep/voice images
  must be pinned and pass the same gate before production use.
- Complete Kiswahili user task sessions; institutional SSO awaits real IdP rules.

See `AUDIT.md`, `ROADMAP.md`, `ORCHESTRATION.md`, and `DEPLOY.md` for evidence,
control flow, and operating steps.
