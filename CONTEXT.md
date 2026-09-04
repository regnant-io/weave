# Weave — what it is today

*Snapshot: 29 August 2026. A description of the system as built, not as planned.*

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

Compose profiles: **default now includes Postgres and Redis** alongside
`backend` and `frontend`; `deep` adds the capability services above; `full` adds
a Celery worker; `build-images` builds the workspace image.

Postgres and Redis were behind `full` until they were moved into the default,
because the default was SQLite with per-process rate limits — fine for one
person and quietly wrong for a class. SQLite has exactly one writer, so two
students sending a message at the same moment serialise and a third waits behind
both; per-process limits multiply the configured number by the worker count.
Neither announces itself; both present as "Weave is slow today". The
zero-service boot is still one command, it is just no longer what you get by
accident.

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

## 3. Tools — 51 of them

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

A library of 22 worked procedures in `services/skills/library/`, as plain
Markdown with front matter. `list_skills` is cheap (names and one-liners);
`read_skill` loads one body. The assistant is instructed to read before
following, and never to claim it applied a skill it has not read.

They are files rather than prompt text because the prompt is paid for on every
turn by every model; a library of twenty procedures would crowd out the
conversation and make small models measurably worse.

**Research and study:** `data-analysis-workflow`, `statistical-test-choice`,
`literature-review`, `research-proposal`, `survey-design`, `academic-writing`,
`exam-revision`, `teach-a-hard-concept`.

**Making things well:** `choose-the-right-output` (which surface a request
belongs on — the decision that goes wrong before a line is written),
`beautiful-visualisation`, `single-file-html`, `knowledge-graph` (React Flow),
`interactive-3d-scene` (Babylon), `interactive-simulation`, `presentation-deck`,
`fix-a-broken-artifact` (repair by editing, with each gate error mapped to its
actual cause), `build-and-ship-software`, `verify-before-shipping`,
`delegate-and-parallelise`, `using-weave-well`.

**Writing and examining:** `academic-kiswahili` (the register, and the habits
that make Kiswahili academic prose read as translated English),
`exam-paper-practice` (NECTA/CSEE command words, mark allocation, and marking
honestly rather than generously).

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

Without Postgres and Redis (development only — see §1 for why this is not a
deployment):

```bash
WEAVE_DATABASE_URL=sqlite:///./var/weave.db WEAVE_REDIS_URL= \
  docker compose up backend frontend --build
```

Fully local with Ollama:

```bash
ollama serve && ollama pull llama3.1
docker compose --profile deep up --build -d
```

With Claude:

```bash
ANTHROPIC_API_KEY=sk-ant-... docker compose --profile deep up --build -d
```

Backend tests: `cd backend && python -m pytest tests` (148 passing).

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

---

## 16. What changed on 29 August 2026

A pass over correctness, capacity and the surface, driven by symptoms that were
each visible and none of which had an obvious cause. Recorded here because the
mechanisms are more interesting than the fixes, and because most of them have
the same shape: something correct in isolation producing the opposite of its
intent in the one situation that mattered.

### Four UI faults with the same character

**Scrolling up during a stream was impossible.** The bottom-pinning hook fenced
its own scroll assignments behind a boolean the scroll handler checked and
cleared on the next animation frame. That works when assignments are rare;
during a stream they are constant, so the fence was never down and a real user
scroll could never unstick the view. Pressing "scroll to bottom" made it worse,
because it re-armed the fence for a 420ms animation. Replaced with two
unambiguous signals: the exact `scrollTop` we last wrote, and direct observation
of wheel, touch, keyboard and scrollbar input.

**Tokens printed on top of each other.** Settled markdown segments carried
`content-visibility: auto` with `contain-intrinsic-size: auto 1px`, so every
off-screen block measured one pixel tall. `scrollHeight` was therefore wrong,
pinning scrolled against a wrong height, and the browser resolved the real
heights mid-paint — between those two states, lines from different blocks
occupied the same pixels. The performance goal it served was already met by
memoising each segment.

**"JavaScript did not load" on a working app.** The banner was hidden by
removing a `no-js` class the server renders onto `<html>`. `className` is part
of the React tree, so every client-side navigation re-committed the server's
value and put the class back — the warning appeared for the first time at the
moment the user proved it false. Now `<noscript>` for scripting-off, and a
head-set timer cleared by a mounted client component for a genuinely dropped
bundle.

**The dashboard peeked before onboarding.** The gate lived in the page
component, below the shared layout, so the whole application painted for a beat
before redirecting a first-run user into the flow meant to introduce it. Moved
to middleware, which decides before anything renders. Onboarding's Skip button
was separately broken: it fired the request that sets the `onboarded` cookie and
navigated in the same tick, so the navigation raced the fetch, lost, and was
bounced straight back.

### Streaming

The Ollama path falls back to a non-streaming request when a stream dies, and
then emitted the whole regenerated answer — including the part already on screen
— so the opening was printed twice, interleaved with itself. It now sends only
the delta, or retracts with `answer_restart` when the retry diverged.

`TurnResult.text` was whatever the FINAL step said, so a model that writes a
paragraph and then calls a tool had that paragraph streamed and then dropped:
the transcript was right until it was reloaded. Every non-empty step is kept.

The Anthropic path did not stream at all, and the "did the engine stream?" test
was a hard-coded comparison against the string `"ollama"` — so its finished
answer was re-emitted through the fake token generator meant for engines that
cannot stream. Engines now declare `streams`.

**Tapestry produced the worst answer in the product.** A supervised turn's
delivered text was every pass concatenated, and models re-orient when handed a
conversation: a continuation restates the problem, a repair restates what was
already fine. At one continuation that is a stray paragraph; at five
continuations and two repair rounds it is the same material up to eight times,
with later copies contradicting earlier ones. Paragraphs repeated by a later
pass are now dropped. The per-phase pass limits also multiplied — 6 + 2×6 =
eighteen generations, a number nobody chose — so there is a ceiling on the
total.

### Concurrency

Independent tool calls run at the same time. Tools opt in via
`Tool.parallel_safe`, off by default and set only on reads that touch neither
the database (one Session, not thread-safe) nor the world. A mixed batch stays
serial; results come back in the order the model asked for them.

Making that safe required two prerequisites, both latent bugs on their own: tool
events now carry the id of the step they belong to (substeps used to attach to
whichever step started most recently), and each call gets its own `ToolContext`
copy rather than mutating `emit` on a shared object.

### Durable turns (`services/orchestration/live.py`)

A turn was owned by the HTTP request that started it, so a refresh, a tunnel
restart or a phone moving from wifi to mobile data cancelled it. For a chat
reply that is a reasonable trade; for a twenty-minute build it means the work,
the installed packages and the spent quota all vanish with no record — and
people learn not to start long jobs, which removes the capability the product is
built around.

A turn is now a first-class object that writes numbered events into a buffer.
Connections attach and read from where they left off, so a reconnect replays
exactly what was missed (`?after=<seq>`). A turn nobody comes back to is still
cancelled, after a grace period long enough to survive a bad handover. Because
losing a connection no longer means anything, Stop had to become explicit: there
is a cancel endpoint, and the client calls it.

The registry is per-process; a reconnect routed to a different worker gets a 404
and the client reloads the thread, which for a finished turn shows the real
answer.

### Delegation (`services/orchestration/subagent.py`)

`delegate` hands one self-contained lookup to a read-only worker whose sources
never enter the caller's conversation. This is a context fix, not an
architectural fashion: comparing four districts means forty pages of raw text
landing in the window the model is answering from, of which about a paragraph
each survives into the answer. Delegates cannot write, run code, produce
artifacts, touch the database, or delegate further — the tool is simply absent
from the set they are given, which is stronger than instructing them not to.

### Artifacts that rendered nothing

A SyntaxError is raised when a script is PARSED, and the model's Babylon scene
code was inlined into the same `<script>` as the harness that reports errors —
so one stray comma took the reporting down with it and the page sat on "Loading
scene…" forever while every layer above reported success. The code is now
compiled server-side with `new Function` before it is sent, lives in its own
`<script>`, and is wrapped async so a scene that awaits a mesh loader is legal
rather than a syntax error. The canvas is `renderCanvas`, because that is the id
in every Babylon sample and therefore the id models type when they look one up
instead of using the one they were handed.

A Vega-Lite spec can be valid, compile cleanly, render without a warning and
produce an SVG with nothing in it — an empty data array, a misspelled field
name, a filter matching no rows. Every layer reported success because from the
outside a blank chart and a real one are both "an SVG". The render service is
the only place that can look at the marks, so that is where the question is now
asked.

**Repair means edit.** The brief used to say "call the tool again with the
corrected version", which does not converge: the rewrite has a new fault about
as often as the original did, so the budget is spent going sideways and the user
watches the same thing break three times in three different ways.
`update_visual` previously handled five of the eleven visual kinds and refused
the rest — including Babylon scenes and HTML pages, the two that break most — so
there was no honest alternative to offer. It now handles every kind, against
source kept for exactly this purpose, and the brief names the id and asks for
the smallest change that fixes the fault.

### Capacity

A `Session` checks out a connection when a transaction begins and returns it on
commit — and in commit-as-you-go mode a plain SELECT opens one. So a single
query early in a turn held a connection through minutes of generation and tool
calls that need no database at all. Released after retrieval, after history is
read, and after each tool call. Added pool sizing and `pool_pre_ping`.

The streaming turn ran on the request's session, from another thread, while the
generator held it too. It now opens and owns its own.

Rate limits were per-process, so N workers allowed N times the configured
number, silently. Buckets move to Redis when `WEAVE_REDIS_URL` is set, with
refill-and-take in a Lua script so it is atomic under exactly the concurrency
that makes limiting matter.

Postgres was never fully set up: only SQLite got the keyword-search index and
the add-missing-column pass, so a Postgres instance had no full-text index and
every keyword search was a sequential scan of the corpus. Its search path also
built an invalid `tsquery` from an empty token list, which was a 500 rather than
no results.

### Credentials

Four routes had no limit of any kind, and they are the four where calling
repeatedly IS the attack. `/auth/otp/verify` was the worst: six digits, a
million values, ten minutes, unlimited guesses. It now has a per-address rate
limit AND an attempt budget attached to the code — the budget is on the code and
not the phone number, because burning a number would let anyone lock a real
person out of their own account by guessing badly on their behalf.

`decode_access_token` raised on a malformed token rather than returning None, so
a corrupt cookie produced a 500 with a traceback. `LocalStorage` tested
containment with a string prefix, which accepts a sibling directory whose name
starts with the root's.

### The chat surface

An assistant turn now expresses the structure it has: what I planned, what I
did, what I found. Adjacent steps are grouped into one collapsible entry —
ordering untouched, because a group ends at the first block that is not a step —
and a finished run of four or more folds to a single line. A group with anything
running stays open, and so does one with a failure: an error behind a chevron is
an error nobody reads. A rule marks where the answer begins, matching the "You"
rule on a user turn.

The steering bar and the live-voice bar were laid out underneath the composer
overlay and had been invisible and unclickable. The transcript padded against a
constant rather than the composer's measured height, so a multi-line draft hid
the last line of the answer. Per-token render cost was proportional to
conversation length, because a callback closing over a freshly-created object
defeated memoisation for every turn.

An empty chat offers four mode-aware openings written as things a person would
type. A new user's model of this product is "a chat window", and a blank page
with a tagline does nothing to change that.
