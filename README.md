# Weave

Bilingual (Kiswahili / English) study + research platform for Tanzanian students
and researchers — with a code-executing data-analysis engine and retrieval over
Tanzanian academic sources.

This repository is a **complete, runnable implementation** of
[`architecture.md`](architecture.md): a FastAPI backend (Gateway + Orchestration +
Retrieval + Analysis + Sandbox Manager) and a Next.js / TypeScript / Tailwind
frontend (App Router, SSR-first, bilingual, low-bandwidth aware). **No Vite**, per
the architecture's explicit constraint.

---

## Quick start (Docker — recommended)

The backend's scientific stack (pandas/scipy/statsmodels/matplotlib) has stable
wheels on Python 3.12, so the backend image pins 3.12. Everything boots with **zero
external services** (SQLite + an offline deterministic LLM engine + a subprocess
sandbox).

```bash
docker compose up --build
```

- Frontend → http://localhost:3000
- Backend API + Swagger docs → http://localhost:8000/docs
- Demo login (seeded): phone `+255700000001`, password `weave-demo-123`

### Choosing the LLM (Ollama / Claude / offline)

`WEAVE_LLM_BACKEND` selects the engine (default `auto`): **Ollama if a local
server is reachable → Claude if `ANTHROPIC_API_KEY` is set → the offline
deterministic engine**. Every branch degrades to offline so it always boots.

**Fully local with Ollama (no API key):**

```bash
ollama serve                 # start the local server
ollama pull llama3.1         # a tool-capable model (qwen2.5, mistral-nemo also work)
# optional, for local retrieval embeddings:
ollama pull nomic-embed-text

docker compose up --build    # auto-detects the host's Ollama via host.docker.internal
```

Force it and/or enable local embeddings:

```bash
WEAVE_LLM_BACKEND=ollama WEAVE_OLLAMA_MODEL=llama3.1 \
WEAVE_OLLAMA_USE_EMBEDDINGS=true docker compose up --build
```

`GET /health` reports the resolved `llm_engine` and `embedding_backend`.

**Claude instead:**

```bash
ANTHROPIC_API_KEY=sk-ant-... docker compose up --build
```

---

## Quick start (local, without Docker)

### Backend

Requires Python 3.12 (the scientific stack has no 3.14 wheels yet).

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed.seed
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local     # points at http://127.0.0.1:8000
npm run dev
```

---

## What actually works, end to end

1. **Auth** — register / login (stdlib scrypt + HS256 JWT) and SMS-OTP flow (OTP
   logged in dev). Token stored httpOnly by the frontend.
2. **Projects** — persistent research workspaces with hypotheses + a rolling
   summary (the "persistent research memory").
3. **Datasets** — upload CSV/XLSX/JSON → object storage → automatic profiling
   (schema, per-column stats). Idempotency keys dedupe mobile retries.
4. **Bilingual chat** — SSE-streamed, student (Socratic) vs researcher (direct)
   modes, model-tiering router, layered system prompt. Both `content_sw` and
   `content_en` are stored per message (bilingual at the data layer).
5. **Retrieval** — hybrid vector + BM25 search with reciprocal-rank fusion over a
   seeded Tanzanian source library, language-aware query expansion, and
   access-status / predatory-journal flags enforced at the data layer.
6. **Code execution** — the model (or the offline engine) emits Python that runs
   in a hardened sandbox against a read-only copy of the dataset, producing
   charts/tables that come back into the chat.
7. **Guardrails** — academic-integrity redirect (student mode), ungrounded-fact
   flagging, predatory-journal checking.

---

## Capabilities & tools (extensible)

Capabilities are registered in a **tool registry** (`services/tools`) and advertised
to the LLM per mode + trust-tier. Each is a thin adapter over a self-hostable
service; adding a capability = adding one `Tool`.

| Tool | Backing service | Status |
|---|---|---|
| `run_analysis` | Sandbox Manager (Python) | working |
| `search_library` | Retrieval (hybrid RAG) | working |
| `check_citation` | Predatory-journal check | working |
| `web_search` | **SearXNG** metasearch | wired; needs `deep` profile |
| `deep_research` | SearXNG + **Browserless** + extraction, iterative loop, SSRF-guarded, streamed | wired; needs `deep` profile |
| `generate_visual` | **Render service** (Vega-Lite → SVG) | wired; needs `deep` profile |
| `generate_deck` | Render service (slides → HTML deck) | wired; needs `deep` profile |
| `query_warehouse` | **DuckDB** (embedded) / ClickHouse | working (DuckDB), read-only SQL guard |

`GET /health` reports the resolved engine, embedding backend, the registered
tools, and which capabilities are currently enabled.

### Deep-capability services (self-hosted)

```bash
# start the heavy services (pulls SearXNG, Browserless/Chromium, Gotenberg,
# MinIO, Qdrant, ClickHouse + builds the Node render service):
docker compose --profile deep up -d

# then point the backend at them and restart it:
WEAVE_SEARXNG_URL=http://searxng:8080 \
WEAVE_BROWSERLESS_URL=http://browserless:3000 \
WEAVE_RENDER_URL=http://render:3100 \
WEAVE_GOTENBERG_URL=http://gotenberg:3000 \
  docker compose up -d backend
```

Security note: web content is **untrusted data, never instructions**; fetches are
SSRF-guarded (private/loopback/link-local/cloud-metadata blocked) and size/time
bounded. Warehouse SQL is read-only (SELECT/WITH only; file/system/DDL blocked).

## Faithful substitutions (documented, drop-in swappable)

The architecture targets cloud infra that can't be provisioned in a from-scratch
local boot. Each substitution keeps the real contract so the production component
is a drop-in swap:

| Architecture (production) | This build (dev default) | Swap point |
|---|---|---|
| PostgreSQL 16 + pgvector | SQLite + numpy-cosine + FTS5 BM25 | `WEAVE_DATABASE_URL`; `services/retrieval` abstracts vector search |
| Firecracker microVM sandbox | Hardened subprocess Sandbox Manager | `WEAVE_SANDBOX_BACKEND=firecracker`; `runner.py` harness is identical |
| Claude via Anthropic API | **Ollama (fully local)** + real Claude SDK + deterministic offline engine | `WEAVE_LLM_BACKEND` |
| S3-compatible object storage | Local filesystem backend | `WEAVE_STORAGE_BACKEND=s3` in `storage.py` |
| Redis token buckets | In-process token buckets | `ratelimit.py` |
| Celery async jobs | Inline profiling/ingestion | same service calls, move to a task |
| Multilingual embedding model | Deterministic hashed n-gram embedding | `services/retrieval/embeddings.py` |

Nothing about the API shape, data model, prompt architecture, sandbox lifecycle,
or security model changes across the swap.

---

## Tests

The suite includes the integration tests architecture §12 requires — real
sandboxed execution against known-good and known-bad code samples.

```bash
# in the backend image / a 3.12 venv with requirements installed:
cd backend && pytest
```

Covers: sandbox precheck + execution + isolation, auth, hybrid retrieval,
orchestration turns (bilingual, SSE, sandbox loop), and the API surface.

---

## Repository layout

```
architecture.md            the design this implements
backend/
  app/
    main.py                FastAPI Gateway
    config.py db.py models.py schemas.py security.py ratelimit.py deps.py storage.py
    api/                   auth, projects, datasets, messages(SSE), analysis, library, citations
    services/
      orchestration/       LLM layer: prompts, router, guardrails, llm engine, orchestrator
      retrieval/           hybrid RAG: embeddings + service
      analysis/            dataset profiling + sandbox interface
      sandbox/             Sandbox Manager: precheck, runner harness, manager
    seed/                  demo user, source library, sample dataset
  tests/                   pytest suite (incl. sandbox known-good/known-bad)
  Dockerfile
frontend/
  src/app/                 App Router pages (landing, auth, chat, projects, datasets, library, settings, admin)
  src/app/api/             route handlers (session proxy, SSE chat proxy, uploads)
  src/components/          client components (chat SSE, prefs, forms)
  src/lib/                 api client, session cookies, i18n, types
  Dockerfile
docker-compose.yml
```

See [`architecture.md`](architecture.md) for the full design rationale; inline
code comments cross-reference the relevant sections.
