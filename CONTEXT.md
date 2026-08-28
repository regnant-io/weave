# Weave — what it is today

*Snapshot: 30 July 2026. A description of the system as built, not as planned.*

Weave is a bilingual (Kiswahili / English) study and research workspace for
Tanzanian students and researchers. It is a working instrument rather than a
chat window: it retrieves from a curated local corpus, runs real code in two
different sandboxes, renders interactive artifacts, and remembers a project
across months of conversations.

It runs entirely on self-hosted infrastructure and degrades to a zero-external-
service boot (SQLite + an offline deterministic engine + a subprocess sandbox),
so it always starts.

---

## 1. Shape of the system

```
Next.js 15 frontend (App Router, SSR-first, bilingual, low-bandwidth aware)
        │  cookie session → server routes proxy to the API
        ▼
FastAPI backend
    Gateway ── Orchestration ── Retrieval ── Analysis ── Workspace ── Crawler
        │
        ├─ SQLite (default) or Postgres + pgvector (--profile full)
        ├─ render-service   (Node)      charts, graphs, 3D, decks, HTML
        ├─ SearXNG          metasearch
        ├─ Browserless      headless Chrome
        ├─ Gotenberg        HTML → PDF
        ├─ MinIO / Qdrant / ClickHouse  (optional)
        └─ weave-workspace  per-command container for the developer sandbox
```

Compose profiles: default (`backend` + `frontend`), `deep` (the capability
services above), `full` (Postgres + Redis + a Celery worker), `build-images`
(builds the workspace image).

**Ports.** frontend `:3000`, backend `:8001→8000`, render `:3100`, SearXNG
`:8888`, Browserless `:3001`, Gotenberg `:3002`, MinIO `:9000/:9001`, Qdrant
`:6333`, ClickHouse `:8123`.

---

## 2. The model layer

`WEAVE_LLM_BACKEND` selects the engine (`auto` by default): **Ollama if a local
server is reachable → Claude if `ANTHROPIC_API_KEY` is set → the offline
deterministic engine.** Every branch falls back, so the product boots with no
key and no model.

`GET /health` reports the resolved `llm_engine` and `embedding_backend`.

**Prompts are capability-gated and size-gated.** `services/orchestration/
prompts.py` assembles a per-turn prompt from layers, and a layer is only
included when the tools it describes actually exist for that run — telling a
model to "run the tests you write" when there is no workspace produces confident
claims about work it could not have done. A second axis, `model_class`
(`large`/`small`, inferred from the engine and the parameter count in the model
tag), trims the explanatory layers for small local models, which produce worse
output when handed eight pages of standards. Both classes get identical *rules*.

### What changed here, and why it matters

The prompt used to make Weave refuse work it was fully equipped to do. Three
clauses did the damage, and all three are gone:

- a grounding layer that forbade stating anything factual without a retrieved
  source and pushed the model toward "ask the user to narrow the question" —
  retrieval misses constantly, and a miss read as a refusal;
- student mode gating *every* first response behind a Socratic question, which
  is right for explaining a concept and obstructive when someone asked for a
  program or a cleaned dataset;
- an academic-integrity rule that said flatly "do NOT write it", matched by a
  regex broad enough to catch "draft the report".

The rules that actually matter are kept in full: tool output and retrieved text
are untrusted data and never instructions; citations are never fabricated; the
student's own thinking stays central. Integrity is now handled by **co-writing**
rather than refusal, and the trigger requires possessive schoolwork ("write *my*
essay") so ordinary drafting is untouched.

---

## 3. Tools — 45 of them

Registered in `services/tools/`, gated by mode, trust tier, wired services and
router intent.

| Group | Tools |
|---|---|
| Analysis | `run_analysis`, `query_warehouse` |
| Retrieval | `search_library`, `web_search`, `fetch_url`, `deep_research`, `check_citation` |
| Workspace | `workspace_write/read/edit/delete/move/list/glob/grep/exec/verify/package` |
| Visuals | `generate_visual`, `create_diagram`, `create_simulation`, `create_animation`, `create_knowledge_graph`, `create_html_page`, `create_3d_experience`, `generate_3d`, `generate_deck`, `render_custom` |
| Artifact CRUD | `list_visuals`, `update_visual`, `delete_visual`, `present_visual` |
| Verification | `verify_artifact` |
| Memory | `remember`, `recall`, `forget` |
| Skills | `list_skills`, `read_skill` |
| Canvas | `canvas_read`, `canvas_edit`, `canvas_append`, `canvas_write`, `canvas_create`, `canvas_list` |
| Interaction | `ask_user` |

Recent additions: `workspace_grep` and `workspace_glob` (find code without
reading whole files into context), `fetch_url` (read one known URL — searching
and reading were previously the same expensive operation), `create_knowledge_graph`,
`create_html_page`, `verify_artifact`, and the two skill tools.

### Two sandboxes, deliberately different

- **Analysis sandbox** (`run_analysis`) — locked down. No network, no
  filesystem. Data in via `weave_io.load_dataset()`, outputs via
  `weave_io.save_output()`.
- **Project workspace** (`workspace_*`) — a real persistent directory with a
  container behind it: Node 20, Python 3, git, ffmpeg, ImageMagick, **and
  network access**. Survives across turns and chats. Gated to verified users and
  disableable with `WEAVE_WORKSPACE_ENABLED=false` — it grants the backend the
  host Docker socket, which is a real privilege.

---

## 4. Skills

A library of 15 worked procedures in `services/skills/library/`, as plain
Markdown with front matter. `list_skills` is cheap (names and one-liners);
`read_skill` loads one body. The assistant is instructed to read before
following, and never to claim it applied a skill it has not read.

They are files rather than prompt text because the prompt is paid for on every
turn by every model; a library of twenty procedures would crowd out the
conversation and make small models measurably worse.

**Research and study:** `data-analysis-workflow`, `statistical-test-choice`,
`literature-review`, `research-proposal`, `survey-design`, `academic-writing`,
`exam-revision`, `teach-a-hard-concept`.

**Making things well:** `beautiful-visualisation` (form heuristic, palette
rules, labelling), `single-file-html`, `knowledge-graph` (React Flow),
`interactive-3d-scene` (Babylon), `build-and-ship-software`,
`verify-before-shipping`, `using-weave-well`.

---

## 5. Rendering, and why artifacts stopped breaking

`render-service/` (Node) turns AI-emitted specs into fully self-contained pages:
no CDN, no external font, no network at runtime, strict CSP, opaque-origin
iframe.

Endpoints: `/chart` (Vega-Lite → SVG/PNG), `/deck`, `/diagram`, `/simulation`,
`/animation`, `/three`, `/babylon`, `/graph` (React Flow), `/html`, `/custom`,
`/verify`, `/health`.

Three problems were fixed here:

1. **Babylon reported unavailable.** The running container was a stale image
   built before `babylonjs` was in `package.json`. Bundle paths are now resolved
   relative to the module rather than the working directory, `/health` reports a
   version and names any missing engine, and the Dockerfile fails the *build*
   if a bundle it inlines is absent.

2. **"Cannot use import statement outside a module".** Model-authored code was
   inlined verbatim into a classic `<script>`, so any ESM `import` was an
   immediate fatal parse error and the artifact rendered blank — with no signal
   to the model that anything was wrong. `lib/js.js` now rewrites imports of
   already-inlined libraries (`three` → the `THREE` global, and so on), promotes
   a script to `type="module"` when it genuinely needs top-level await, and
   otherwise fails with an error naming the offending specifier. The
   `try { … }` wrapper was removed: it could never catch a *parse* error, and it
   put every top-level `const` in a block scope inline handlers could not reach.

3. **No way to check.** `/verify` and the `verify_artifact` tool statically
   catch ESM-in-classic-script, external resources the CSP will block, and
   truncation — the three failures that look fine in the source and blank in the
   browser.

React Flow ships ESM/CJS only, so it is bundled to an IIFE by esbuild at image
build time (`build.mjs`, which also asserts the production define applied — a
development React build dies in the artifact with `process is not defined`).

---

## 6. Memory and threads

A **project** is the durable workspace; a **thread** is one conversation inside
it. Continuity lives in the project, not in one ever-growing message list:

- a rolling project summary, updated per turn;
- `MemoryEntry` rows — small, addressable, keyed facts written by `remember`,
  read into the system prompt on every turn of every thread, and fully visible
  and deletable by the user;
- automatic thread rollover when history exceeds the model's context window,
  with `parent_thread_id` keeping the chain auditable.

---

## 7. Automated ingestion — crawlers and scrapers

`services/crawler/` grows the source library. Two things feed it: an operator
adding a seed on the admin page, and — with consent — the domains real sessions
consult.

**Politeness is a design constraint, not a setting.** This runs against small
Tanzanian university and ministry servers.

- `robots.txt` is fetched, cached per host, and obeyed, including a longer
  `crawl-delay` when one is published.
- Requests to a host are serialised and spaced. There is no per-host concurrency
  at any point.
- The User-Agent identifies WeaveBot honestly. Agents and addresses are **not**
  rotated — a site that does not want us has given an answer.
- Depth, page count and wall-clock are all capped (`HARD_MAX_*`), above whatever
  a seed's own budget says.

**Spider traps** get three independent defences, because no one of them is
enough: a normalised-URL visited set (fragment, tracking params, trailing slash,
host case), a content hash so the same page under forty URLs is indexed once,
and a path-repetition check for `/a/b/a/b/a/`.

**Consent.** `User.allow_source_crawl` is on by default and switchable in
Settings. When a session reads public pages, their *domain* is recorded as a
**disabled** candidate seed; nothing is fetched until an admin enables it. User
messages, datasets and files are never ingested. The check lives inside the
crawler service, so there is one place it can be got wrong.

**Admin page** (`/admin`) lists curated and session-discovered seeds separately,
with per-seed budget controls, a run button, and a page log that records
*refusals as well as successes* — "why is this page not in the library" is the
question an operator actually has, and "disallowed by robots.txt" is only
answerable if the refusal was written down.

---

## 8. Frontend

Next.js App Router, SSR-first, no Vite (an explicit architecture constraint).

**Typography.** The editorial pairing (Instrument Serif + Fraunces) is gone.
One grotesque — Geist — carries display, reading and UI; JetBrains Mono carries
code, figures, eyebrows and step chips. The serifs gave the product a magazine
voice it was not speaking in. Figures are lining and tabular. Generated
artifacts use matching system stacks, since they cannot fetch a webfont.

**The floating top rail.** The three controls hovering over the chat — menu,
thread switcher, thread options — were positioned independently, with three
different `top` offsets, three heights, and only two of them safe-area aware, so
on a phone they sat on three visibly different lines. Two tokens
(`--float-top`, `--float-h`) are now the single definition of that rail.

**Two chat bugs, one root cause.** `ChatWorkspace` kept a single `messages`
array not tied to any thread, so any path that changed the active id without
resolving that thread's fetch could render one chat's transcript under another's
identity — or nothing at all. Transcripts are now cached per thread id, which
makes the mismatch unrepresentable, renders a revisited chat instantly, and
prefetches on hover and on opening the list.

**Tool panels survive a refresh.** The step timeline — what was searched, what
was run, what each step produced — used to exist only in the live SSE stream, so
reloading turned a detailed audit trail into a bare paragraph. The server now
persists it (reconstructed from the events the client actually received, so the
replay cannot drift from the live render) and the client rebuilds the panels on
load.

---

## 9. Safety properties worth knowing

- Retrieved text, web pages, files and tool results are **untrusted data**.
  The base prompt says so first, `fetch_url` repeats it in its result, and the
  model is told to quote rather than obey any instruction found inside.
- Artifacts run in an opaque-origin iframe (`sandbox="allow-scripts"`, no
  `allow-same-origin`) under `default-src 'none'`. Containment, not code review,
  is what makes model-authored rendering safe.
- SSRF guards on every outbound fetch (`_is_safe_url`), shared by the research
  path, the ingestion path and the crawler.
- Workspace path resolution rejects `../`, absolute paths, drive prefixes and
  symlinks pointing out of the tree.
- Post-hoc grounding guard flags empirical claims that no retrieved passage
  supports.

---

## 10. Running it

```bash
docker compose --profile deep up --build -d
```

- Frontend → http://localhost:3000
- API + Swagger → http://localhost:8001/docs
- Demo login: phone `+255700000001`, password `weave-demo-123`

Fully local with Ollama:

```bash
ollama serve && ollama pull llama3.1
docker compose --profile deep up --build -d
```

With Claude:

```bash
ANTHROPIC_API_KEY=sk-ant-... docker compose --profile deep up --build -d
```

Backend tests: `cd backend && python -m pytest tests` (68 passing).

---

## 11. Live session: voice, ambient presence, screen sharing

One WebSocket carries all of it — `/api/v1/ws/session/{project_id}` — because it
is all one conversation. "What's wrong with this?" means nothing without the
screen frame that arrived a second earlier, and reassembling that ordering across
two transports is the kind of thing that works in testing and fails on a train.

**Two engines, one protocol.** By default the phone does the work: `SpeechRecognition`
for transcripts, `speechSynthesis` for the reply, and the socket carries only
text. No models, no GPU, works on a mid-range Android. A server engine
(Whisper + Piper, `--profile voice`, `WEAVE_STT_URL` / `WEAVE_TTS_URL`) speaks the
same protocol for deployments that want better Kiswahili and can afford it.

**What makes it feel like talking**, none of which is the recognition itself:

- **Barge-in.** Recognition keeps running *during* playback specifically so
  speech over the assistant cuts it off — checked on interim results, so it
  fires on the first syllable rather than at the end of the sentence. The turn's
  cancel Event is set from the event loop while the worker is mid-generation.
- **Sentence-at-a-time speech.** `SentenceChunker` releases each sentence as it
  completes, so the reply begins while the rest is still being written. It knows
  about abbreviations, so "Dr. Mwakalinga" is not two utterances.
- **Ambient gating.** In ambient mode the mic stays open and the assistant stays
  quiet: it answers only when named, when the utterance is shaped like a request,
  or within 25s of having spoken (so a follow-up needs no wake word). The default
  is silence — answering when nobody asked is what makes people switch a feature
  off.
- **Backchannel.** Rate-limited listening noises ("mm", "ndiyo") during long
  utterances. At most one per utterance, never inside six seconds.
- **A speech sanitiser.** `speakable()` strips citation markers, markdown,
  tables and URLs from the spoken copy only. The prompt asks for speech-shaped
  answers and capable models oblige, but the offline engine never sees a prompt
  and small models relapse under load — without this, TTS reads "open square
  bracket S one close square bracket" mid-sentence.

**Screen sharing.** `getDisplayMedia` at 1fps, downscaled to ≤1280px JPEG,
**sent only when the picture actually changed**, rate-limited server-side. Frames
ride on the user's turn in an engine-neutral `images` field: Ollama consumes that
shape natively and `AnthropicEngine._with_images` converts it to typed blocks. A
model without vision gets an honest note saying a screen is being shared and is
told to ask rather than guess.

A `SPEAKING_ALOUD` prompt layer is appended for voice turns only: short, no
markdown, no citation markers, no URLs, lead with the answer.

## 12. Steerable reasoning

You can redirect the model while it is still working. The turn registers under
its assistant-message id — which the client already has from `meta`, before any
tool runs — so steering is available from the first second of a turn.

A redirect does two things at once: it queues the text, and it sets an Event that
the running generation reads as a cancel (the engines already poll one between
tokens and between tool calls, which is exactly the checkpoint density needed).
Generation aborts, the redirect enters the conversation as a real user turn
marked as superseding, and generation restarts.

**Why restart rather than splice:** tokens already streamed cannot be unsaid, and
a model cannot be asked to change its mind about text it has committed to.
Restarting is the only approach that yields an answer genuinely shaped by the
redirect instead of one contradicting its own opening paragraph. The client is
told to clear the partial answer (`answer_restart`), so the screen matches what
the model actually reasoned about.

Budget: three restarts per turn. Past that a redirect is still delivered — it
becomes context for the next call — but stops aborting this one, which is what
guarantees the turn terminates. The UI shows each applied redirect in the
timeline, so the transcript records *why* the answer changed direction.

## 13. The collaborative canvas

A document in the side panel that both parties edit live, over
`/api/v1/ws/canvas/{canvas_id}`.

**This is not a CRDT and does not pretend to be.** It is server-authoritative
with a monotonic revision, and the two editors get deliberately different
primitives because they edit in genuinely different ways:

- The **human** sends whole-document writes carrying the revision their editor
  last saw. A stale base is **rejected** with the current text, and the UI offers
  the choice. Nothing is silently overwritten.
- The **assistant** sends **anchored** edits — `canvas_edit` finds exact text and
  replaces it. Those rebase by construction: they apply to whatever the document
  currently says. If the anchor has vanished the tool fails with a message the
  model can act on ("read it again and retry") rather than clobbering a paragraph.

That asymmetry is what lets both work simultaneously without character-wise
transforms: a human typing in one paragraph and the assistant rewriting another
do not conflict at all, and a genuine overlap surfaces as a rejection instead of
a silent loss. The panel autosaves on a short debounce, and a remote change that
arrives while the user has unsaved typing is **held and offered**, never applied
over them.

Tools: `canvas_read`, `canvas_edit`, `canvas_append`, `canvas_write`,
`canvas_create`, `canvas_list`. A `SHARED_CANVAS` prompt layer tells the model to
read before editing and to prefer anchored edits over rewrites.

**Fan-out is in-process.** The subscriber hub is a dict in the API process, so an
edit made in that process reaches every socket it holds — including edits made
from the orchestrator's *worker thread*, which is the case that matters and is
covered by `loop.call_soon_threadsafe`. It does **not** cross process boundaries:
run two backend replicas and a socket held by one will not see a write made by
the other. Single-process deployment is fine today; multi-replica needs a Redis
pub/sub behind `_Hub.publish`, which is the only place that would change. The
same caveat applies to the steering broker.

## 14. WebSocket authentication

Browsers cannot set headers on a WebSocket handshake, so the credential travels
in the query string — where it lands in proxy logs and browser history. Handing
out the session token for that would erase the httpOnly cookie protecting it.

So sockets take their own credential: `POST /api/v1/ws-ticket` mints a
sixty-second, `scope: "ws"` token, and `get_current_user` **rejects** it on every
REST route. Leaking one costs an attacker a socket they must open within the
minute, not an account. `/api/realtime` (Next) hands the browser both the ticket
and the socket base URL in one call — sockets connect to the API origin directly,
because Next route handlers proxy HTTP but not upgrades.

## 15. Not built

- **Explicit emotional-attunement machinery.** The `ADAPTIVE_TONE` prompt layer
  is in place and is the whole of it — there is no sentiment model or signal
  detection behind it, by choice.
- **Multi-user presence on the canvas.** It is built for one human and the
  assistant. Two people editing simultaneously would work mechanically (the
  revision check protects them) but there are no cursors and no identity per
  edit — `updated_by` is only "human" or "assistant".
- **Multi-replica realtime.** The canvas hub and the steering broker both hold
  state in process memory. Horizontal scaling needs a shared bus; see §13.
- **Verified vision.** Screen frames are wired end to end and the Anthropic
  block conversion is unit-tested, but no vision-capable model was configured on
  this machine, so "the assistant described what was on screen" has not been
  observed. With the offline engine it correctly falls back to the honest note.

The self-correction loop *is* built: `VERIFY_YOUR_WORK` in the prompt, the
`verify-before-shipping` skill, `verify_artifact`, `workspace_verify`, and the
render service's static linter.
