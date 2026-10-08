# Weave repository audit

## 2026-09-26: orchestration, datasets and desktop release

This pass prioritised abandoned plans, false completion, dataset correctness,
runtime portability and a newly built Windows desktop distribution. Earlier
production risks below remain applicable.

| Severity | Root cause | Fix and evidence |
|---|---|---|
| High | Repeated gap notices removed unresolved work; one deliverable closed unrelated plan steps. | Persistent acceptance-driven gaps, cited tool evidence, dependencies and honest bounded termination; agent regressions. |
| High | Plan/progress existed only until the final message commit; continued SQL tasks lost intent-gated tools and calculation evidence. | Short checkpoint commits, same-context recovery, retained outputs and bounded numerical evidence; turn-level database and continuation regressions. |
| High | Independent generation repair budgets competed with the task supervisor. | Removed `verification.py` and post-generation gate; latest-version inspection, tests and self-audit now drive task continuation. |
| High | Streamed provisional success could remain when final stored text said incomplete; shared filenames could attach another output's verification. | Exact artifact identity, complete provisional-text replacement and explicit incomplete plan state; backend and browser regressions. |
| High | Dataset readers disagreed on encoding/nulls/schema; malformed, profiling or failed datasets could reach execution. | Shared strict reader, ready-state enforcement, bounded sampled CSV statistics and actual source/run identifiers; real Python/SQL format tests. |
| High | SQL aliases could bypass external-access filtering. | DuckDB external access disabled and configuration locked; adversarial query regressions, bounded query duration and guaranteed connection close. |
| Medium | Frozen Python omitted pytest and lazy analysis libraries; POSIX shell reset bundled-tool PATH and Docker lacked `python`. | Packaged modules, CPython-compatible workspace imports/options, preserved PATH and Docker alias; runtime and release smoke checks. |
| Medium | Frozen Windows sandbox stripped required system settings; bundled node preload paths lost backslashes. | Minimal Windows system environment, writable temporary configuration and correctly quoted preload paths; source regressions and isolated packaged checks. |
| Medium | Visual source sidecars became phantom list entries; absent PDF converter silently returned HTML as successful PDF. | Metadata-only visual listing, HTML-only deck schema without a converter and explicit PDF failure; real storage and adapter regressions. |
| Medium | Stale staging included removed code; cross-OS packaging produced an incompatible frozen backend. | Fresh verified staging and host/target guard; production build and Windows package validation. |
| Medium | Desktop navigation accepted lookalike origins; absent tray, orphan subprocesses, port collisions and Docker reconnects caused silent failures. | Exact-origin navigation, explicit exit/process cleanup, collision rejection and capability reprobes; desktop lifecycle/runtime tests. |

Validation: 278 backend tests passed; 18 render tests and 4 desktop lifecycle
tests passed; 8 browser journeys passed (3 mobile duplicates intentionally
skipped); frontend typecheck, lint and production build passed. Production npm
audits reported no vulnerabilities. Windows installer and bundled-runtime smoke
results are recorded in `CHANGELOG.md` after packaging.

Limits: Docker is unavailable on this host; macOS/Linux installers require native
hosts. JSON/Excel currently parse fully into memory and Excel analysis uses the
first worksheet. Checkpoints keep bounded excerpts, not an unlimited execution
log; critical-history overflow remains an explicit recovery boundary. Provider
availability and real-model semantic correctness cannot be established by offline
regressions. Local desktop workspace commands run under the OS user's account.

Audit date: 2026-09-14. Scope covered the FastAPI API and data boundaries, auth,
orchestration, tool routing, sandbox/workspace execution, web retrieval/crawling,
artifact verification, Next.js rendering and API proxy routes, the Node render
service, dependencies, Docker Compose, and the Kamatera deployment path.

## Findings fixed during the audit

| Severity | Finding | Resolution |
|---|---|---|
| Critical | A committed ngrok credential was present in three tracked files. | Removed from the working tree; deployment now requires `NGROK_AUTHTOKEN`. Revoke and history purge remain external actions. |
| Critical | The normal Compose deployment mounted `/var/run/docker.sock` into the public API while workspace execution was available to verified users. | Socket mount and workspace opt-in moved to the local override; production preflight rejects workspace enablement unless explicitly allowed. |
| Critical | Production could run model-written Python in an in-process-host subprocess; the advertised Firecracker backend is unimplemented. | Analysis is separately configurable and production startup rejects the subprocess path. |
| High | A self-registering user could submit an institution ID and obtain institutional trust; that trust also granted admin access. | Registration rejects institution claims and admin endpoints require the `admin` role. |
| High | Tool visibility was treated as authorization. A stale/hallucinated call could bypass intent, trust, service, delegated-scope, or plan-surface filters. | Every layer now rechecks its allowlist immediately before execution. |
| High | Web URL validation covered the first URL only, so redirects could target private services. Bodies were capped only after complete buffering. | Every redirect is revalidated and response bytes are bounded during streaming. |
| High | Browserless crawled attacker-controlled pages on the application network. | JavaScript crawling now falls back to SSRF-checked HTTP pending an egress-isolated browser pool. |
| High | WhatsApp accepted unsigned POST bodies. | Meta HMAC verification is mandatory and fails closed when unconfigured. |
| High | A production boot could seed or retain a known public admin/demo password. | Demo seeding is local-only and deployed startup rejects a surviving known demo account. |
| High | Password signup immediately granted a verified capability tier, and failed production SMS delivery logged the live OTP. | New accounts remain anonymous until OTP verification; deployed SMS fails closed and never logs the code. |
| High | Any signed-in user could replace the process-wide Ollama host, redirecting later users' prompts. | Runtime host settings are admin-only, hidden from normal users, URL-validated, and immutable in deployed environments. |
| High | Generated HTML was sandboxed only when embedded; opening it in a new tab ran it on the authenticated application origin. | HTML/SVG responses now carry a CSP sandbox with an opaque origin and no remote network, the frontend proxy preserves it, and iframe permissions match offline render requirements. |
| High | Editing a message deleted all later project messages, including sibling threads. | Truncation is scoped to the anchor message's thread with a regression test. |
| Medium | Artifact UI state said verified when Browserless was down and only static lint ran. | Runtime execution is reported separately; static-only artifacts are explicitly unverified. |
| Medium | Automatic deep-research events were overwritten when the agent run completed. | Pre-generation events are retained in the stored tool audit log. |
| Medium | Dataset upload read the whole file into memory and idempotency collided across users/projects and grew without bound. | Uploads stream from the spooled file; cache keys include user/project and have a fixed ceiling. |
| Medium | Parallel registration of the same account could pass both optimistic lookups and leak a database integrity error as HTTP 500. | Database uniqueness remains authoritative and races now roll back as stable HTTP 409 conflicts. |
| Medium | Client IP rate limits trusted arbitrary `X-Forwarded-For`. | Forwarded headers are ignored unless the deployment explicitly trusts its proxy. |
| Medium | The local token-bucket map retained one entry per observed identity forever. | The fallback limiter now has a fixed LRU ceiling; Redis buckets already expire. |
| Medium | Frontend lint was interactive and render service had no test/build contract. | Added ESLint flat config, render contract tests, and deterministic build scripts. |
| Medium | Frontend and renderer dependency trees contained known high/critical advisories. | Upgraded Next/React/render packages and lockfiles; production npm audits are clean. |
| Medium | Model-authored Markdown URLs were rendered without an application allowlist. | Links/images now accept only expected HTTP, mail, fragment, or signed-artifact forms; image requests suppress the referrer. |
| Medium | Repaired artifacts kept the same URL, but chat URL deduplication discarded their new verification state; live voice also changed markup during hydration. | Existing artifact cards now update in place, and browser capability detection runs after hydration. Both paths have browser regressions. |
| Medium | The frontend rebuild helper used `git reset --hard` and globally pruned Docker build cache, silently deleting operator work and unrelated cache state. | Rebuilds now require a fast-forward pull and replace only the frontend service. |

Request payload lengths are now bounded for auth, chat, steering, analysis, canvas,
project, thread, memory, and citation inputs. Internal service ports are bound to
host loopback in Compose, Node images install from lockfiles with `npm ci`, common
browser security headers are set, and API schema/docs are disabled when deployed.

## Open production risks

- Git history still contains the revoked-value candidate for the leaked ngrok
  credential; working-tree removal does not invalidate a credential.
- SSRF checks still have a DNS-resolution/connect race. Use an outbound proxy or
  connect to a pinned resolved address before treating this as a complete boundary.
- The remote analysis contract has no deployed isolated runner yet. Developer
  workspaces likewise need a separate host before production enablement.
- Full Redis/Celery failover, production-origin rollback, S3 lifecycle policy, and
  representative Postgres retrieval latency still require the target environment.
- Optional development images (Browserless, voice, MinIO) remain outside the
  production pin gate. Any promoted optional service must be digest-pinned and
  scanned in its registry first.
- JavaScript crawling remains disabled because application-level SSRF checks do
  not close DNS rebinding for a general browser.
- Human Kiswahili task-completion evaluation and institutional SSO requirements
  need participating users and an actual identity provider.

## Validation evidence

- Backend pytest suite and clean Alembic upgrade/downgrade suite pass locally,
  with the environment-dependent Redis test skipped.
- Frontend: ESLint, TypeScript, and Next.js 16 production build pass.
- Playwright registration/OTP/onboarding, route-gate, dataset-upload, admin-denial,
  logout, and multi-chat isolation journeys pass across desktop Chromium and a
  Pixel 7 profile. The suite found and drove removal of a Google Fonts build
  dependency and a parallel-registration identity collision.
- Render service: health, chart, diagram, simulation, animation, graph, deck,
  HTML-page, Babylon, and remote-script rejection contracts pass, along with the
  browser bundle build.
- The 20-case bilingual deterministic evaluation passes. The eight-query live
  Postgres pgvector benchmark records 100% recall@6, 9.0 ms p50, and 117.3 ms p95;
  representative target data is still a deployment gate.
- Dependency audits: frontend and renderer report zero production npm advisories;
  pip-audit reports no known vulnerability in the resolved Python requirements.
- Bandit reports no high-severity issue. Its medium finding is the deliberate `exec`
  in the analysis runner, which is why production preflight now disables that path.
- Production image-pin and secret scanners pass. The three runtime images contain
  zero fixable high/critical findings under the pinned Trivy gate. `bash -n`
  deployment checks pass and both Compose documents validate.
- A fresh production-shaped Docker stack reached the migration head without seed
  users; Postgres pgvector/HNSW, Redis replay across API restart, Celery execution,
  MinIO storage, backup/restore, non-root containers, Caddy HTTPS, and the complete
  WebSocket edit flow were exercised successfully. Browserless, voice, and remote
  execution boundaries remain environment-dependent and disabled for production.

Implementation order and acceptance gates are maintained in `ROADMAP.md`.
