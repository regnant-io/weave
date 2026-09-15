# Weave delivery roadmap

Status date: 2026-09-14. This is an implementation ledger, not a wish list.
`Implemented` means repository work is complete and locally verified. `Deployment
gate` names work that needs production infrastructure or an external account.

## Stage 0 — remove unsafe and false-success behaviour

Status: **implemented**.

- Tool authorization is enforced again at execution, including delegated scope,
  intent, trust tier, available services, and requested output surface.
- Registration cannot self-claim institutional trust or administration. Admin
  APIs require the explicit admin role; SMS and WhatsApp fail closed.
- Redirects are SSRF-checked hop by hop and streamed within byte limits.
  Browserless navigation remains disabled until its network is egress-isolated.
- Dataset uploads stream to storage and use durable owner/project/request-hash
  idempotency. Chat edits stay inside one thread.
- Direct HTML/SVG artifacts receive an opaque-origin CSP sandbox. Static checks
  and real browser execution are reported as different verification states.
- Production preflight rejects local code execution, unsafe workspace settings,
  development secrets, SQLite, missing Redis/S3, and the public demo account.
- Secret, dependency, authorization, rendering, upload, and rate-limit regressions
  are checked in tests and CI.

External incident action: revoke the previously committed ngrok credential and
coordinate a history rewrite. Removing it from the current tree cannot revoke it.

## Stage 1 — production boundary and delivery

Repository status: **implemented except for isolated runner and workspace-host
deployment**.

- Alembic owns deployed schemas. Containers upgrade to the checked-in head before
  starting; startup refuses a database behind the head.
- Caddy provides one TLS origin for frontend HTTP and backend WebSockets. Only the
  proxy trusts forwarded client addresses.
- Production Compose defaults to Postgres, Redis, S3-compatible storage, the
  background worker, disabled local analysis, and disabled developer workspaces.
- Postgres backup and disposable-restore verification scripts are checked in.
- Python and Node dependency graphs are locked. Production base images, Postgres,
  Redis, and Caddy are digest-pinned and a CI check prevents them drifting.
- CI runs tests, migrations, bilingual evaluation, browser journeys, npm/pip
  audits, Bandit, secret scanning, Compose validation, CycloneDX SBOM output, and
  fixable high/critical runtime-image CVE rejection.
- The analysis client implements a signed, replay-resistant remote-runner contract
  with code/dataset hashes and hard result limits.
- A fresh production-shaped Docker deployment passed migrations, readiness, the
  no-demo-user check, backup/restore, MinIO S3 operations, Celery execution, and a
  complete HTTPS/WSS register-edit-resume-delete journey through Caddy.

Deployment gates:

1. Deploy a gVisor/Firecracker or equivalent runner that satisfies the signed
   `/v1/runs` contract; prove no network, read-only input, tenant separation,
   CPU/memory/PID/time limits, and destruction after each run.
2. Deploy developer workspaces on a separate host with a scoped job API, quotas,
   image allowlists, egress rules, and immutable audits before enabling them.
3. Repeat the locally completed backup/restore and TLS/WebSocket drills on the
   provisioned staging origin, including rollback under the deployment runbook.
4. Enforce the checked-in Trivy image gate in the release environment and apply an
   equivalent admission policy to promoted registry images.

## Stage 2 — durable orchestration

Repository status: **implemented; broker failover drill remains**.

- Redis stores live-turn metadata, ordered replay events, cancellation, steering,
  and resume cursors. Celery owns the producer when Redis is configured, so an API
  process restart does not end the turn.
- A live Celery job and Redis stream replay across an API-container restart passed
  against the Docker stack.
- Upload idempotency, webhook receipts, job state, outbox delivery, refresh-token
  sessions, and admin invitations are durable database records.
- Profiling, ingestion, crawling, summaries, channel delivery, and streamed turns
  run as tracked jobs. Celery retries with bounded exponential backoff and records
  exhausted work as `dead_letter`; the admin dashboard exposes the state.
- WhatsApp provider IDs are deduplicated and replies use a transactional outbox.
- Access tokens last 15 minutes; opaque refresh tokens rotate, reuse revokes the
  family, logout revokes server-side, and the browser refreshes on restore.

Deployment gate: run a multi-worker Redis/Celery fault drill that kills the API
and active worker in turn, then proves replay without event loss/duplication and
redelivery without duplicated channel messages.

## Stage 3 — retrieval, rendering, and data scale

Repository status: **implemented; production measurements remain**.

- Postgres uses pgvector cosine search with an HNSW index and stored full-text
  vectors with GIN; SQLite retains deterministic development fallbacks.
- S3-compatible storage uses tenant-prefixed keys. Artifact capabilities expire
  cryptographically and object cleanup retains a bounded local cache.
- The complete S3 storage contract passed against MinIO, and renderer contract
  tests passed in its non-root production container.
- Renderer inputs, strings, arrays, nodes, rows, concurrency, wait time, response
  bytes, and wall time are bounded. Health reports limits and current load.
- PDF pages, extracted text, parse time, web bytes, and crawler queue growth are
  bounded, with rejection reasons recorded.
- `eval/benchmark_retrieval.py` measures bilingual recall@k and p50/p95 and refuses
  to treat SQLite as production unless explicitly requested.
- The eight-query bilingual pgvector benchmark passed on live Postgres at 100%
  recall@6, 9.0 ms p50, and 117.3 ms p95. Representative target data remains the
  basis for selecting a production embedding.

Deployment gates:

1. Run the retrieval benchmark on representative staging Postgres content and
   record recall and p95 before selecting a production multilingual embedding.
2. Record sustained render/PDF latency and memory under production container
   limits; malformed-input and complexity-limit contracts already pass.
3. Restore JavaScript crawling only behind a DNS-pinning outbound proxy or an
   egress-isolated Browserless network.
4. Add ClickHouse only after measured DuckDB/Postgres workloads miss their budget.

## Stage 4 — product quality and expansion

Repository status: **core contracts implemented; user research and SSO remain**.

- Tool inputs use a useful JSON-Schema subset and failures return stable categories
  with retryability. Tool, retrieval, model-fallback, job, and channel metrics are
  available in the admin dashboard.
- Playwright covers registration, OTP, onboarding, public/private gates, dataset
  upload, admin denial, logout, multi-chat isolation, repaired-artifact state,
  hydration, desktop, and Pixel 7 overflow. Parallel identities are
  collision-resistant. Builds no longer contact Google Fonts.
- The release drills now exercise exact-cursor stream resume over Redis/Celery;
  the live run replayed 109 post-disconnect events without a gap or duplicate.
- The deterministic bilingual evaluation set now contains 20 cases across routing,
  teaching, integrity, literature, data, and ordinary assistance and runs in CI.
- High-risk orchestration concerns have explicit service boundaries and tests. A
  larger chat-client/state-machine split should proceed only with feature work that
  benefits from it, rather than as an unmeasured rewrite.

Product gates:

1. Run task-completion sessions with Kiswahili-speaking university students and
   researchers; add anonymized failure patterns to the golden set.
2. Add institutional SSO only after an IdP supplies metadata, role/deprovisioning,
   and account-linking requirements.

## Release decision

CI passing is necessary but does not authorize a public launch. Promotion also
requires zero unresolved P0 findings, a recent restore drill, the public TLS/WS
journey on the target environment, Redis/Celery failover evidence, and continued
disablement of any execution capability whose isolated runner has not passed
hostile fixtures.
