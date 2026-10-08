# How Weave orchestration works

This describes the executable control flow after the 2026-09-26 hardening pass.
`architecture.md` explains the product design; this file explains which component
owns each transition and what happens when it fails.

```mermaid
sequenceDiagram
    participant UI as Next.js UI/BFF
    participant API as FastAPI gateway
    participant Redis as Redis live state
    participant Worker as Celery worker
    participant Orch as Orchestrator
    participant Tools as Authorized tools
    participant Agent as Task supervisor
    participant DB as Postgres

    UI->>API: start turn (access session, project, text)
    API->>DB: persist user + assistant placeholder
    API->>Redis: create turn metadata/event cursor
    API->>Worker: dispatch durable stream producer
    UI->>API: follow SSE cursor
    Worker->>Orch: process turn
    Orch->>DB: load thread/project/dataset context
    Orch->>Orch: classify intent + integrity rule
    Orch->>Tools: execute against current allowlist
    Tools-->>Agent: tool results and stored outputs
    Agent->>Tools: inspect latest output / run validation
    Tools-->>Agent: execution evidence or concrete failures
    Agent->>DB: checkpoint goals, steps, evidence, outstanding work
    Agent->>Tools: continue unfinished work / edit detected defects
    Orch->>DB: commit answer, sources, plan, tool audit
    Orch->>Redis: done event + expiring replay state
    API-->>UI: ordered events; reconnect resumes by cursor
```

## Turn ownership

The API authenticates the user and allocates the assistant message/turn ID. With
Redis configured, it writes live metadata and dispatches `weave.run_stream_turn`;
the Celery worker owns generation. SSE connections only follow the event log, so
disconnecting does not own or cancel the work. Resume, cancellation, and steering
check the stored user ID before touching a turn.

Without Redis, development uses an in-process registry and a daemon thread. This
fallback makes a zero-service local boot possible. Production preflight rejects it.

## One processing pass

1. Resolve the requested thread and the selected model's real context window.
2. Persist the user message and create the assistant placeholder.
3. Classify `general`, `concept`, `literature`, or `data`; decide model tier,
   retrieval, and sandbox need. Statistical teaching does not open a sandbox unless
   the user asks to calculate, plot, or analyse data.
4. Load an owned dataset and retrieve bilingual local passages when relevant.
5. Apply the student integrity rule. It changes the teaching strategy while keeping
   the subject available.
6. Build the service map and tool schemas for this user, mode, trust tier, intent,
   and delivery surface.
7. Classify chat, small actions, analysis, coding, visual artifacts, and substantial
   tasks. Chat and small actions skip planning and critic calls even at deep effort.
   Substantial tasks use understand → plan → execute → inspect → validate →
   self-audit → fix/polish → recheck → deliver.
8. Re-authorize every tool at execution time. Schema validation rejects malformed
   model arguments with a stable error code and retryability hint.
9. The supervisor calls `verify_artifact` on each latest HTML output after a work
   pass. Generation does not run a separate repair gate. Static checks alone are
   `unverified`; browser or visual failures remain unfinished work. At deep effort,
   a vision-capable model inspects the screenshot for concrete visual defects.
10. Commit bilingual answer fields, citations, artifacts, plan, tool audit, context
    accounting, and thread rollover before emitting completion.

## Completion, recovery, and resource boundaries

Plans include a goal, constraints, numbered steps, dependencies, and acceptance
checks. `update_plan` cites successful numbered tool events when closing work;
tests and inspection support acceptance checks. Producing one file cannot close
unrelated exports, research, or additional deliverables. Re-planning retains
unfinished obligations and completed work.

The supervisor retains unresolved gaps until resolved. Repeated prose, identical
tool results, and failed retries do not count as progress. Pass limits and repeated
no-progress attempts terminate with an explicit incomplete result and remaining
work, never a successful completion. A browser outage, failed test, placeholder,
unrecovered execution failure, or unaudited revision cannot be hidden by a
confident closing paragraph. Source changes invalidate prior workspace checks;
visual edits require inspection of the new version.

Short transactions persist checkpoints in `messages.plan._task_state`, including
bounded tool evidence and stored outputs. They do not wait for final generation.
After a restart or resource boundary, `continue`, `resume`, or `finish` in the same
task thread restores its latest incomplete checkpoint. Project and dataset IDs
must match; a different dataset starts fresh. Recovery preserves useful files and
uses a new execution allowance. Network reconnect still uses the SSE cursor;
checkpoints recover work, not the interrupted provider stream.

## Durable control-plane records

| Record | Purpose | Duplicate/failure rule |
|---|---|---|
| `job_records` | User/operator state for background work | bounded backoff; exhausted tasks become `dead_letter` |
| `idempotency_records` | Upload retry safety | key is scoped by owner/project and bound to request hash |
| `webhook_receipts` | Provider event ownership | provider + event ID is unique |
| `outbox_events` | Channel side effects | commit with app state; delivery retries independently |
| `auth_sessions` | Refresh-token family | rotate each use; reuse and logout revoke server-side |
| Redis turn keys | ordered events/cancel/resume | owner checked; bounded event history and TTL |
| Redis steering keys | redirects during generation | owner checked; three restart budget |
| Message task checkpoint | goal, dependencies, outputs and completion evidence | short commits; same-thread/project/dataset recovery |

## Failure semantics

- A broker submission failure becomes a failed durable job; deployed API requests do
  not silently fall back to local execution.
- Worker loss requeues an unacknowledged Celery task. Application errors retry with
  exponential backoff and eventually remain visible as dead letters.
- Model-provider failure emits a fallback metric and labels the deterministic answer.
- Retrieval misses are reported as empty/filtered instead of fabricating grounding.
- WhatsApp is acknowledged only after receipt/outbox commit. Missing production
  outbound credentials fail delivery and remain visible; they are never logged as a
  successful send.
- Artifact download capabilities include an expiry and the response streams from
  local or S3 storage under a sandboxing CSP.

## Adding a capability

Implement a small tool adapter, declare its input schema and eligibility, and add it
to the service map. Keep authorization in the registry/execution boundary rather
than relying on prompt instructions. If it creates an artifact, expose output files
and a stable visual ID so the supervisor can inspect revisions. If it can outlive
a request or cause an external side effect, give it
a tracked job and/or transactional outbox record. Add its latency/failure category
to operational metrics and include one denial and one success regression.
