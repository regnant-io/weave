# Weave — Roadmap & Status

Status of every roadmap track. ✅ = built & verified, 🟡 = built (needs live infra to
fully verify), ⚪ = documented stub / next step.

---

## Track A — Reliability & correctness

- ✅ **A1 Intent-gated tools** — the registry advertises tools per router intent +
  trust tier (`Tool.intents`). Web tools (`web_search`, `deep_research`) are offered
  only for `literature`/`general` intent, `query_warehouse` only for `data`. The
  auto-web-fallback fires only for `literature` — so a concept question ("explain
  standard deviation") no longer triggers a crawl.
- ✅ **A2 Stop / regenerate / edit** — client `AbortController` → backend `GeneratorExit`
  → a `cancel` Event checked in the Ollama stream loop aborts promptly. Regenerate
  reuses the last user turn and drops the old answer; edit truncates from a message
  (`DELETE …/messages/from/{id}`) and resends. UI: Stop button, Regenerate, inline edit.
- 🟡 **A3 Real embeddings + trafilatura** — Ollama `nomic-embed-text` embeddings are
  wired and enabled (`WEAVE_OLLAMA_USE_EMBEDDINGS=true`); they activate when the embed
  model is present on the Ollama server, else fall back to the deterministic embedding.
  `trafilatura` now installed for clean web extraction.
- ✅ **A4 SearXNG hardening** — curated engine set (disabled startpage/google-cse/
  deviantart/unsplash/pexels; kept bing/ddg/wikipedia + image engines), 6 s timeout.
  Cut log errors ~500 → ~20/session.
- ✅ **A5 Artifact lifecycle + limits** — HMAC-signed artifact URLs (`?sig=`), a
  background TTL sweeper (3-day GC of charts/decks/pdfs), and per-turn caps on sandbox
  runs (6) and web calls (12).

## Track B — Intelligence quality

- ✅ **B1 Bilingual eval harness** — `backend/eval/` golden set + runner scoring
  language correctness, grounding, integrity-guard, and tool discipline. Run:
  `python -m eval.run_eval`.
- 🟡 **B2 Ingestion pipeline** — `services/ingestion` fetches a URL (SSRF-guarded),
  extracts HTML (trafilatura) or PDF (pypdf), chunks + embeds + indexes. Triggerable
  from the **Admin** dashboard or the `weave.ingest_source` Celery job. (Scheduled
  connectors/crawlers are the next increment.)
- ✅ **B3 Grounding guard v2** — per-sentence check: any empirical claim (statistic,
  year, named body) must lexically overlap a retrieved passage, else it's surfaced as
  potentially unsupported. No-grounding local-fact claims still flagged.
- ✅ **B4 Project memory** — hypotheses CRUD (status cycle open→supported→refuted),
  lit-review notes, and an LLM `resummarize` endpoint; full UI on the project page.

## Track C — Production infrastructure

- 🟡 **C1 Postgres + pgvector** — `WEAVE_DATABASE_URL=postgresql+psycopg://…` works
  (models are DB-agnostic; sparse search uses tsvector on PG). `pgvector/pgvector:pg16`
  image + `--profile full`. (Native pgvector index is the next step; dense search is
  currently Python cosine, fine at MVP scale.)
- 🟡 **C2 Celery + Redis** — `app/tasks.py` with a graceful `dispatch()` that enqueues
  to Redis when configured (`--profile full` runs a `worker` service) or runs inline in
  a thread otherwise. Jobs: source ingestion, project re-summarize.
- ⚪ **C3 Sandbox hardening** — subprocess backend is the dev path; Firecracker/gVisor
  are the documented production backends (`WEAVE_SANDBOX_BACKEND`, `manager.py` stub).
- 🟡 **C4 Observability** — OpenTelemetry auto-instrumentation (FastAPI + httpx),
  no-op unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- 🟡 **C5 SMS OTP** — Africa's Talking adapter (`WEAVE_SMS_PROVIDER=africastalking`),
  falls back to logging in dev.

## Track D — Reach & growth

- 🟡 **WhatsApp channel** — `/api/v1/channels/whatsapp` webhook (verify + receive) over
  the channel-agnostic orchestrator; maps sender → user + project, runs a turn, replies
  via the WhatsApp Cloud API (logs when no token set).
- ✅ **Offline PWA** — manifest + service worker (cache-first shell, network-first
  navigations, API never cached), installable, offline-tolerant.
- ✅ **Admin/ops dashboard** — real data (stats, source library + ingestion status,
  sandbox audit log) + ingest-a-URL, gated to admin/institutional.
- ⚪ **SAML SSO** — SP-metadata + ACS stub endpoints; needs an institutional IdP (v2).

## Cross-cutting

- ✅ **Prompt-injection defense** — crawled passages sanitised of injection directives
  before reaching the model; the base system prompt marks all tool/grounding content
  as untrusted data, never instructions.
- 🟡 **Streaming parity** — Ollama streams token-live; Anthropic/offline stream the
  finished answer word-by-word (visual parity). Native Anthropic streaming is next.
- ✅ **DB concurrency** — SQLite `busy_timeout=30s` + `synchronous=NORMAL`.

---

## Open decisions (architecture §14)
1. Self-host Firecracker vs. buy a sandbox API (biggest scope lever).
2. Embedding model for Swahili quality — needs a real eval, not benchmark faith.
3. Institutional data-access terms (COSTECH/UDSM) → API vs. scrape ingestion.
