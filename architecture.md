# Weave Platform — Full System Architecture

**Working name:** Weave (placeholder — named for the way the product weaves together Kiswahili and English, student and researcher, local sources and reasoning, into one thread)
**Scope:** Bilingual (Kiswahili/English) study + research web platform for Tanzanian students and researchers, with a code-executing data analysis engine and retrieval over Tanzanian academic sources.
**Explicit constraint:** No Vite anywhere in the toolchain.
**Status:** v1 architecture for MVP build, with noted v2 extension points.

---

## 1. Design Principles

These principles are referenced throughout the doc — every component choice below is justified against one of these.

1. **One reasoning engine, two framings.** Student mode and researcher mode are UI/prompt/pacing layers over a single execute-and-explain core loop, not two products.
2. **Low-bandwidth first, not low-bandwidth eventually.** Every screen must render something useful on a throttled 3G connection. This shapes the frontend rendering strategy (Section 4) and the API payload design (Section 5).
3. **Retrieval before generation, always, for factual/citation content.** The model is never allowed to answer a "what does the data say" or "what does the literature say" question from parametric memory alone when local grounding is available.
4. **Code execution is a hostile-input problem, not a feature.** Section 8 treats the sandbox as the security-critical core of the system, not an implementation detail.
5. **Everything is bilingual at the data layer, not the display layer.** Language is a first-class column/field everywhere content is stored, not a runtime translation pass.

---

## 2. Technology Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend framework | **Next.js (App Router), served via its built-in server, not static export** | Explicitly avoids Vite. Gives SSR for low-bandwidth first paint, built-in route handlers, React Server Components to cut client JS. |
| Frontend bundler | Next.js's own build pipeline (Webpack or Turbopack, both bundled — not Vite) | Comes with the framework, no separate bundler decision needed. |
| UI language | TypeScript | Type safety across a bilingual, schema-heavy app reduces a whole class of bugs (e.g. mixing up `sw`/`en` fields). |
| Styling | Tailwind CSS (utility classes, no CSS-in-JS runtime cost) | Keeps client JS bundle small — matters on 3G. |
| Backend API | **Python — FastAPI** | Best ecosystem fit for the data-analysis engine (pandas, numpy, scipy, statsmodels) and for LLM orchestration libraries. Async-native, OpenAPI docs for free. |
| LLM orchestration | Custom thin orchestration layer (not LangChain) calling the Anthropic API directly | A bespoke ~500-line orchestrator is easier to reason about, debug, and keep bilingual-aware than a general-purpose framework carrying assumptions we don't need. |
| Primary LLM | Claude (via Anthropic API), model selected per task tier (see Section 6.4) | Strong multilingual reasoning, native tool use / code execution support, function calling for the analysis engine. |
| Database | **PostgreSQL 16** | Relational integrity for users/projects/citations; native JSONB for flexible bilingual content and analysis metadata; pgvector extension for embeddings — one database instead of two. |
| Vector search | `pgvector` extension inside Postgres | Avoids running a separate vector DB (Pinecone/Weaviate) for MVP scale; one fewer service to operate, one fewer bill. |
| Object storage | S3-compatible storage (AWS S3 or a local/regional provider) | Uploaded datasets, generated charts, exported PDFs. |
| Cache / queue | Redis | Session cache, rate limiting, job queue backing (via Celery or RQ) for long-running analysis/retrieval jobs. |
| Background jobs | Celery workers (Redis broker) | Data analysis, document ingestion/embedding, and literature-search jobs run async so the request/response cycle stays fast on slow connections. |
| Code sandbox | **Firecracker microVMs**, orchestrated by a small internal service (see Section 8) | Hardware-virtualized isolation, sub-second boot, purpose-built for exactly this "run untrusted short-lived code" problem (this is what AWS Lambda and Fly.io Machines are built on). |
| Delivery / CDN | Regional CDN (e.g., Cloudflare) in front of static assets and API | Reduces latency and data cost for Tanzanian users; Cloudflare has good East African PoP coverage. |
| Auth | Self-hosted auth (email/password + OTP via SMS) using `Authlib`/JWT, no third-party social login as primary path | Many students won't have Google/institutional SSO reliably wired up; SMS OTP is more broadly reachable than email in this context. Institutional SSO (SAML) added in v2 for university partners. |
| Deployment | Docker containers on a managed Kubernetes cluster (or simpler: a managed container platform like Fly.io / Render for MVP, migrate to k8s at scale) | Start simple, keep the architecture container-native from day one so migration later doesn't require a rewrite. |
| Observability | OpenTelemetry → Grafana/Loki/Tempo stack (self-hosted) or a hosted equivalent | Cost-sensitive project; self-hosted observability avoids per-seat SaaS pricing. |

**Why not Vite, explicitly:** Vite is a frontend dev-server/bundler. Next.js includes its own bundling (Webpack/Turbopack) and its own dev server, so choosing Next.js already satisfies "no Vite" without needing a workaround — this isn't a constraint that fights the rest of the stack.

---

## 3. High-Level Architecture

```
                                   ┌─────────────────────────┐
                                   │      Cloudflare CDN      │
                                   │  (static assets, cache,  │
                                   │   DDoS protection, WAF)  │
                                   └────────────┬─────────────┘
                                                │
                          ┌─────────────────────┴─────────────────────┐
                          │                                           │
                 ┌────────▼────────┐                        ┌─────────▼─────────┐
                 │   Next.js App    │                        │   FastAPI Gateway   │
                 │ (SSR + RSC pages,│───── REST/JSON ───────▶│  (auth, routing,    │
                 │  minimal client  │                        │  rate limiting)     │
                 │  JS bundles)     │                        └─────────┬──────────┘
                 └──────────────────┘                                  │
                                            ┌─────────────────────────┼─────────────────────────┐
                                            │                         │                         │
                                   ┌────────▼────────┐    ┌───────────▼───────────┐   ┌─────────▼─────────┐
                                   │  Orchestration    │    │  Retrieval Service     │   │  Analysis Service   │
                                   │  Service           │    │  (RAG over TZ sources) │   │  (dataset → code →   │
                                   │  (LLM calls,        │    │  pgvector + BM25       │   │  chart → explain)    │
                                   │  mode routing,       │    └───────────┬───────────┘   └─────────┬─────────┘
                                   │  bilingual layer)    │                │                         │
                                   └─────────┬────────────┘                │                         │
                                            │                         │                         │
                          ┌─────────────────┼─────────────────────────┼─────────────────────────┘
                          │                 │                         │
                 ┌────────▼────────┐ ┌──────▼───────┐        ┌────────▼────────┐
                 │  Anthropic API    │ │  PostgreSQL    │        │  Sandbox Manager  │
                 │  (Claude models)  │ │  + pgvector    │        │  (Firecracker      │
                 └───────────────────┘ └───────┬────────┘        │  microVM pool)      │
                                              │                 └────────┬────────┘
                                     ┌─────────▼─────────┐               │
                                     │  Redis (cache,      │      ┌───────▼────────┐
                                     │  queue, sessions)   │      │  S3-compatible   │
                                     └─────────┬─────────┘      │  object storage   │
                                              │                 │  (datasets,       │
                                     ┌─────────▼─────────┐      │  charts, PDFs)    │
                                     │  Celery Workers      │      └──────────────────┘
                                     │  (ingestion, embed,  │
                                     │  long analysis jobs) │
                                     └─────────────────────┘
```

**Request flow for the core "upload data → ask a question → get analysis" loop:**

1. Browser uploads a CSV/XLSX to the FastAPI gateway → streamed to S3, a `Dataset` row created in Postgres, a lightweight profiling job queued (Celery).
2. User asks a question (Swahili, English, or mixed) in the chat UI → request hits the Orchestration Service.
3. Orchestration Service builds a context: dataset schema/profile, conversation history, user mode (student/researcher), language preference → calls Claude with tool definitions for the sandbox.
4. Claude decides what code to run (e.g., "run a Shapiro-Wilk test, then a Mann-Whitney U since normality failed") → Orchestration Service sends that code to the Sandbox Manager.
5. Sandbox Manager spins up (or reuses a warm) Firecracker microVM, executes the code against a read-only mount of the dataset, captures stdout/stderr/generated files (charts as PNG/SVG), tears down or recycles the VM.
6. Results go back to Claude as a tool result → Claude produces the explanation in the requested language/register → Orchestration Service streams the response (text + chart URLs) back to the browser via Server-Sent Events.
7. Everything (question, code run, result, explanation) is persisted to the user's Project workspace (Section 9) for later reference.

---

## 4. Frontend Architecture

### 4.1 Rendering strategy (bandwidth-first)

- **Server-rendered by default.** Pages are React Server Components; only the chat input, streaming response renderer, and chart interaction widgets ship as client components. This keeps the initial JS bundle small.
- **Streaming responses via Server-Sent Events (SSE)**, not WebSockets — SSE is simpler to reconnect on flaky mobile networks and works over plain HTTP/1.1, which matters more than the marginal latency win of WebSockets here.
- **Aggressive response compression:** Brotli at the CDN layer, plus a "lite mode" toggle that renders charts as static PNG (server-generated) instead of interactive client-side chart components, for users on very constrained connections.
- **Offline-tolerant drafts:** Chat input and in-progress project notes are held in IndexedDB and retried on reconnect, so a dropped connection mid-typing doesn't lose work. (This is local browser storage, not a backend feature — no server dependency.)
- **No client-side routing framework beyond Next.js's own** — avoids shipping a second router.

### 4.2 Page/route map (App Router)

```
/                          landing + mode selection (student / researcher)
/auth/login, /auth/register, /auth/verify-otp
/app/chat/[projectId]      main chat interface (bilingual toggle, mode indicator)
/app/projects              project workspace list
/app/projects/[id]         persistent research memory view (hypotheses, datasets, lit review)
/app/datasets/[id]         dataset profile view (schema, stats, upload history)
/app/library               curated Tanzanian source library browser
/app/settings              language preference, citation style, institution linking
/admin/*                   internal moderation/ops dashboard (separate auth scope)
```

### 4.3 Bilingual UI mechanics

- A persistent language-state object (not a page-level locale routing scheme like `next-intl`'s URL-prefix mode) since the *same conversation* needs to move between languages mid-thread.
- Every message object carries `{ content_sw, content_en, original_language }` — the UI renders whichever the user has selected, computed once server-side, not re-translated client-side.
- Static UI chrome (buttons, labels) uses a standard i18n library (`next-intl`) for the SW/EN toggle — this part *is* just translation, unlike the dynamic conversation content.

### 4.4 Accessibility & device reality

- Design breakpoints start at 360px width (common low-end Android screens), not 768px.
- All core flows tested against Chrome's "Slow 3G" throttle profile as a CI gate (Lighthouse CI in the pipeline, Section 12).
- No feature is client-JS-only; if JS fails to load, the page still shows server-rendered content and a graceful "reduced functionality" message rather than a blank screen.

---

## 5. Backend / API Architecture

### 5.1 Service boundaries

Four internal services behind the FastAPI gateway, each independently deployable:

1. **Gateway** — auth, request validation, rate limiting, routing to the other three. This is the only service exposed publicly.
2. **Orchestration Service** — owns all LLM calls, prompt construction, mode logic (student vs researcher), conversation state.
3. **Retrieval Service** — owns the RAG pipeline over Tanzanian sources (Section 7).
4. **Analysis Service** — owns dataset handling and the sandbox interface (Section 8).

Why split rather than one monolith: the Analysis Service has fundamentally different scaling and security needs (it talks to the sandbox layer and needs tight resource limits) from the Orchestration Service (which is mostly I/O-bound waiting on the Anthropic API). Splitting lets them scale and be hardened independently without over-engineering an MVP into a large microservice mesh — four services is a deliberately small number.

### 5.2 API design

- REST + JSON for all request/response endpoints; SSE for streaming chat responses; no GraphQL (adds complexity the bilingual/mode logic doesn't need).
- Every payload includes a `language` field explicitly — never inferred silently, since silent inference is exactly the "translation afterthought" problem this product is trying to avoid.
- Idempotency keys required on dataset upload and analysis-run endpoints, since mobile connections retry requests.

**Representative endpoints:**

```
POST   /api/v1/auth/register
POST   /api/v1/auth/otp/verify
POST   /api/v1/projects
GET    /api/v1/projects/{id}
POST   /api/v1/projects/{id}/datasets            (multipart upload → S3)
GET    /api/v1/datasets/{id}/profile
POST   /api/v1/projects/{id}/messages             (SSE stream response)
POST   /api/v1/analysis/run                        (internal-facing, called by Orchestration)
GET    /api/v1/library/search?q=...&source=costech,udsm,nbs
POST   /api/v1/citations/check                     (predatory-journal flagging)
```

### 5.3 Rate limiting & abuse control

- Redis-backed token-bucket rate limiting per user and per IP, tiered by auth status (anonymous browsing of `/app/library` allowed at low limits; chat/analysis requires verified account).
- Sandbox execution requests are rate-limited separately and more strictly than chat requests, since they're the most expensive/dangerous call in the system.

---

## 6. Bilingual Reasoning / Orchestration Layer

### 6.1 Why a custom orchestrator instead of a framework

The bilingual mode-switching and student/researcher pacing logic is domain-specific enough that a general framework (LangChain, LlamaIndex) would mostly add abstraction overhead without solving the actual hard part — which is prompt design and evaluation for Kiswahili academic register, not chain composition. The orchestrator is a well-tested internal library, not a product dependency.

### 6.2 System prompt architecture

Layered system prompt, assembled per request:

```
[Base identity + safety layer]           — fixed, never overridden by user input
   ↓
[Mode layer: student | researcher]        — pacing, permissiveness, Socratic vs direct
   ↓
[Language register layer]                 — academic Kiswahili terms (BAKITA glossary
                                              injection when the topic has standardized
                                              terminology), or English academic register
   ↓
[Grounding layer]                         — retrieved passages from Retrieval Service,
                                              with explicit citation requirements
   ↓
[Project memory layer]                    — summarized prior hypotheses/results for this
                                              project (kept short via rolling summarization,
                                              not full history replay)
   ↓
[Tool definitions]                        — sandbox execution tool, citation-check tool,
                                              retrieval-search tool
```

### 6.3 Student mode vs researcher mode — concrete prompt differences

| Dimension | Student mode | Researcher mode |
|---|---|---|
| Answer style | Socratic first pass; full answer only after the student attempts or explicitly asks to skip | Direct answer with reasoning shown, no gating |
| Datasets | Curated/sample or small student-uploaded sets | Any uploaded dataset, larger size limits |
| Citation requirement | Light — points to textbook/syllabus concept | Strict — every empirical claim must cite a retrieved source, flagged if it can't |
| Curriculum grounding | Tagged to NECTA/CSEE syllabus where applicable | Not applicable |
| Pacing | Checks understanding before advancing ("does that make sense before we go to step 2?") | No pacing checks |

### 6.4 Model tiering (cost control)

- **Lightweight/fast model tier** for: intent classification (is this a student conceptual question, a data question, a literature question?), simple factual Q&A, UI micro-interactions.
- **Frontier model tier** for: the actual Socratic teaching dialogue, code generation for analysis, literature synthesis, and anything producing citable/gradeable output.
- A router step (cheap classification call) decides tier per turn, keeping average cost per conversation down without degrading the moments that matter.

### 6.5 Guardrails specific to this product

- **Academic integrity guard:** in student mode, the orchestrator detects "write my essay/assignment for me" style requests and routes to Socratic mode regardless of phrasing, rather than relying on the base model's judgment alone — this is a product policy, not just a safety default.
- **Hallucination guard for local facts:** any claim that looks like a statistic, law, curriculum requirement, or named local institution must trace to a retrieved passage; if retrieval returns nothing relevant, the model is instructed (and a post-hoc classifier double-checks) to say so explicitly rather than answer from general knowledge.
- **Predatory journal flag:** citation-check tool cross-references suggested/uploaded sources against known predatory-journal lists (e.g., Beall's-list-derived and updated community lists) before a researcher is allowed to cite them uncritically.

---

## 7. Retrieval Architecture (RAG over Tanzanian Sources)

### 7.1 Source library (v1 scope)

- University of Dar es Salaam institutional repository (open-access theses/papers)
- COSTECH research database (where API/scrape access permits)
- NBS (National Bureau of Statistics) published datasets and reports
- Ministry of Education curricula (NECTA/CSEE syllabus documents)
- Selected Tanzanian open-access journals
- (v2) Local case law, additional university repositories, WHO/World Bank data for cross-referencing

### 7.2 Ingestion pipeline

```
Source connector (per-source scraper/API client, runs on schedule via Celery beat)
   → raw document store (S3, versioned)
   → text extraction (per format: PDF via the same extraction approach as the
      internal pdf-reading tooling, HTML cleaning, table extraction for NBS data)
   → chunking (semantic chunking, ~400-600 tokens, section-aware for theses/reports)
   → embedding (multilingual embedding model — must handle Swahili and English well;
      evaluated explicitly on Swahili academic text, not assumed from general benchmarks)
   → pgvector upsert + BM25 (Postgres full-text search) index for hybrid retrieval
   → metadata tagging: source, access status (open/paywalled), publication date,
     language, predatory-journal flag status
```

### 7.3 Retrieval strategy

- **Hybrid search:** vector similarity (pgvector) combined with keyword/BM25 (Postgres `tsvector`), reciprocal-rank fusion to merge — pure vector search underperforms on precise terminology/statistic lookups that academic queries often need.
- **Language-aware retrieval:** query is embedded once, but retrieval also runs a translated-query pass when the user's query language doesn't match a source's dominant language, so a Swahili question can still surface an English-only NBS report.
- **Access-status surfacing:** every returned passage carries an open/paywalled label so the UI (and the model's answer) can be explicit about what the user can actually reach — this was an explicit differentiation goal and is enforced at the data layer, not left to the model to remember to mention.

### 7.4 Freshness

- NBS and government sources re-crawled on a scheduled basis (weekly/monthly depending on source update cadence); institutional repositories re-crawled less frequently (monthly), since theses/papers don't change once published.

---

## 8. Sandbox Design (Code Execution)

This is the most security-critical subsystem in the platform — untrusted, model-generated code is executed against user-uploaded data. It is designed as its own hardened service, not a library call.

### 8.1 Isolation technology choice

**Firecracker microVMs** (the same technology underlying AWS Lambda) rather than plain Docker containers or a shared Python process:

- Containers share the host kernel; a container-escape vulnerability is a full host compromise. A microVM has its own kernel and hardware-virtualized boundary — meaningfully stronger isolation for arbitrary generated code.
- Firecracker microVMs boot in ~125ms, fast enough to spin up per-execution without devastating latency, which a full traditional VM could not do.
- Each execution gets a **fresh microVM**, never a reused one across users — no state leakage between one researcher's dataset and another's.

### 8.2 Sandbox Manager service

A small dedicated internal service responsible for the full lifecycle:

```
Analysis Service ──▶ Sandbox Manager
                         │
                         ├─ 1. Pull a warm microVM from a pre-booted pool
                         │     (pool kept warm to hide boot latency from the user)
                         │
                         ├─ 2. Attach a READ-ONLY copy-on-write mount of the
                         │     specific dataset (never the original S3 object,
                         │     never other users' data — mount scope is
                         │     enforced by the Sandbox Manager, not by the
                         │     generated code's own logic)
                         │
                         ├─ 3. Inject the code via a control-plane RPC
                         │     (code never touches a shared filesystem the
                         │     VM could persist across runs)
                         │
                         ├─ 4. Execute with strict resource limits:
                         │       - CPU: 1 vCPU capped
                         │       - Memory: 512MB–2GB depending on dataset size tier
                         │       - Wall-clock timeout: 30s default, 120s for
                         │         explicitly flagged "heavy" analysis jobs
                         │       - No network access from inside the VM at all
                         │         (outbound network is fully disabled — the
                         │         sandbox cannot exfiltrate data or fetch
                         │         arbitrary code)
                         │       - Disk write limited to an ephemeral scratch
                         │         volume, wiped on VM teardown
                         │
                         ├─ 5. Capture stdout, stderr, exit code, and any files
                         │     written to a designated /output directory
                         │     (charts, result tables) — nothing else is
                         │     retrieved from the VM
                         │
                         ├─ 6. Destroy the microVM (never reuse post-execution,
                         │     even for the same user's next request) and
                         │     replace it in the warm pool
                         │
                         └─ 7. Return structured result to Analysis Service:
                               { stdout, stderr, exit_code, output_files[],
                                 execution_time_ms, resource_usage }
```

### 8.3 Execution environment inside the VM

- Minimal Linux image with a pinned Python 3.x runtime and a fixed, vetted package set: `pandas`, `numpy`, `scipy`, `statsmodels`, `matplotlib`, `seaborn` — **no arbitrary `pip install`** at execution time. If a package isn't in the pinned image, the code can't use it; the image is updated and re-vetted on a controlled release cycle, not on demand.
- No shell access exposed to the generated code beyond the Python interpreter itself — code runs as a submitted script, not as arbitrary shell commands, closing off a large class of injection concerns.
- Filesystem inside the VM is otherwise empty/minimal — no host tooling, no credentials, no way to discover anything about the host environment even if code tried to probe it.

### 8.4 Defense in depth (beyond the VM boundary itself)

1. **Static pre-check** on generated code before it ever reaches the sandbox: reject code containing `import os`, `subprocess`, `socket`, `open()` calls outside the designated I/O helper functions, or other clearly out-of-scope constructs. This is a cheap first filter, not a substitute for the VM boundary — belt and suspenders, not either/or.
2. **Structured I/O contract**: the model is instructed (via the tool definition) to read data only through a provided `load_dataset()` helper and write output only through a provided `save_output()` helper, rather than raw file paths — makes both generation and static-checking more predictable.
3. **No secrets ever present in the VM image or environment** — the sandbox has zero knowledge of API keys, database credentials, or anything else in the broader system, so even a full VM compromise (extremely unlikely given the isolation model, but assume it happens) yields nothing of value.
4. **Output size caps** — generated charts/files capped (e.g., 10MB) before being pulled back, to prevent resource-exhaustion via absurd output generation.
5. **Audit log** of every execution (user, code hash, dataset id, resource usage, result hash) retained for abuse investigation, stored separately from the execution path itself.
6. **Pool isolation by trust tier** — anonymous/free-tier executions draw from a more resource-constrained pool than verified institutional accounts, limiting blast radius of abuse from unverified signups.

### 8.5 Why not simpler alternatives (documented reasoning, not just the choice)

- **Plain Docker/gVisor:** gVisor (used by Cloud Run) is a reasonable middle ground and worth reconsidering if Firecracker's operational overhead proves too high for a small team — noted here as the fallback option, not dismissed. Plain Docker alone is not acceptable given kernel-sharing risk with genuinely untrusted, model-generated code.
- **A hosted "code interpreter" API** (e.g., a third-party sandbox-as-a-service): a legitimate v1 shortcut to avoid operating Firecracker in-house, trading some cost and a vendor dependency for much lower operational burden. Worth evaluating against build-vs-buy economics before committing engineering time to self-hosting — flagged here as the single biggest "reduce scope" lever in this whole architecture if the team is small.
- **In-process `exec()` sandboxing** (e.g., RestrictedPython): rejected outright — language-level sandboxes for Python have a long history of escape vulnerabilities and are not adequate isolation for this threat model.

---

## 9. Data Model (Core Entities)

```
User
 ├─ id, phone, email, password_hash, role (student|researcher|both),
 │  institution_id (nullable), preferred_language, created_at

Institution
 ├─ id, name, type (secondary|university), curriculum_tag (e.g. NECTA/CSEE)

Project                              -- "persistent research memory"
 ├─ id, user_id, title, mode (student|researcher), created_at
 ├─ hypotheses[]        (JSONB: text_sw, text_en, status, created_at)
 ├─ summary             (rolling LLM-generated summary, kept short for context reuse)

Dataset
 ├─ id, project_id, s3_key, original_filename, row_count, column_profile (JSONB),
 │  uploaded_at, size_bytes

Message
 ├─ id, project_id, role (user|assistant), content_sw, content_en,
 │  original_language, created_at, tool_calls (JSONB)

AnalysisRun
 ├─ id, message_id, dataset_id, code, stdout, stderr, output_files[],
 │  execution_time_ms, status, created_at

Source (retrieval library)
 ├─ id, title, url, source_type (udsm|costech|nbs|journal|gov),
 │  access_status (open|paywalled), language, predatory_flag (bool),
 │  ingested_at

Citation
 ├─ id, project_id, source_id (nullable if external), style (APA|Harvard|...),
 │  flagged_predatory (bool)
```

---

## 10. Security & Privacy

- **Data residency awareness:** uploaded research datasets may contain sensitive survey/health data; storage bucket region and encryption-at-rest are configured explicitly, and a data retention/deletion policy is documented and user-facing, not just implied.
- **Encryption:** TLS everywhere in transit; S3 server-side encryption at rest; Postgres encrypted volumes.
- **PII minimization:** phone number used for OTP is stored hashed where possible for lookup, not held in plaintext logs.
- **Least privilege between services:** Analysis Service can talk to the Sandbox Manager and S3; it cannot talk to the Anthropic API directly or read other services' data — enforced via network policy in the container platform, not just convention.
- **Dependency/package pinning** for both the app services and the sandbox image, with scheduled vulnerability scanning (e.g., Trivy) in CI.

---

## 11. Cost Considerations (Tanzania-specific)

- CDN + regional caching prioritized specifically to reduce **user-side data costs**, not just server latency — this is a product commitment, not a generic performance nice-to-have, given that mobile data cost was an explicit differentiation goal.
- Model tiering (Section 6.4) and sandbox warm-pooling both exist as much for **operating cost control** as for latency — a bootstrapped/institution-funded product in this market cannot assume Silicon-Valley-scale LLM spend per user.
- Consider a **WhatsApp Business API channel as a v2 add-on**, reusing the same Orchestration Service behind a different thin adapter — the architecture above deliberately keeps the orchestration layer channel-agnostic (it doesn't assume a browser) so this extension doesn't require a redesign.

---

## 12. CI/CD & Environments

- **Environments:** `dev` → `staging` → `production`, with staging running against a scrubbed/synthetic copy of production-shaped data (never real student data) for realistic testing.
- **CI pipeline:** lint/typecheck → unit tests → integration tests (including a suite that runs real sandboxed code execution against known-good/known-bad code samples) → Lighthouse CI on Slow-3G profile → deploy to staging → manual promote to production.
- **Sandbox image releases** are a separate, more tightly gated pipeline than app deploys, given their security sensitivity — package updates to the execution image go through explicit review, not the normal app CD cadence.

---

## 13. Phased Build Plan (Architecture-Aligned)

| Phase | Scope |
|---|---|
| **v0 (prototype)** | Single Next.js + FastAPI service, one hosted code-interpreter API instead of self-hosted Firecracker, small hand-curated source library (10–20 documents), no auth beyond a demo login. Goal: validate the core loop feels genuinely different, per the earlier pressure-test discussion. |
| **v1 (MVP)** | Full architecture above minus WhatsApp channel and SAML SSO; self-hosted Firecracker sandbox; ingestion pipeline live for UDSM repository + NBS + one journal source; student and researcher modes both live. |
| **v2** | WhatsApp channel adapter, institutional SSO, expanded source library (case law, more repositories), virtual-lab simulations, offline-capable PWA mode. |

---

## 14. Open Decisions Requiring Input

These are flagged rather than silently decided, since they materially change cost/timeline:

1. **Self-host Firecracker vs. buy a hosted sandbox API for v1** — biggest scope lever in the whole plan (Section 8.5).
2. **Embedding model choice for Swahili quality** — needs an actual evaluation pass against real academic Kiswahili text before committing; general multilingual benchmark scores are not sufficient evidence on their own.
3. **Institutional partnership status** (COSTECH/UDSM) for data access — affects whether ingestion is API-based or scrape-based, and the legal terms under which content can be retrieved/cited.
4. **Monetization model** (free/ad-free institutional licensing vs. freemium) — affects the rate-limiting tiers in Section 5.3 and the sandbox pool-isolation tiers in Section 8.4.
