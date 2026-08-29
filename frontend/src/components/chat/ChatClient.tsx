"use client";

import {
  memo,
  useCallback,
  useDeferredValue,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  Artifact,
  Citation,
  Dataset,
  Effort,
  Language,
  Message,
  Plan,
  WebImage,
} from "@/lib/types";
import type { ServicePrefs } from "@/lib/services";
import { DEFAULT_SERVICES } from "@/lib/services";
import type { AskUserRequest, Block, ChatTurn, StepBlock } from "@/lib/chatTypes";
import {
  isArtifactBlock,
  isAsk,
  isStep,
  isText,
  turnArtifacts,
  turnText,
} from "@/lib/chatTypes";
import { contextFor, fetchCatalog, type ModelCatalog } from "@/lib/models";
import PanelDock, { usePanelDock } from "./panels/PanelDock";
import { categorise, PANEL_META, PANEL_ORDER, panelCounts, type PanelId } from "./panels/panels";
import AskUserCard from "./AskUserCard";
import Composer from "./Composer";
import InlineArtifact from "./InlineArtifact";
import LiveBar from "./LiveBar";
import Markdown from "./Markdown";
import PlanRail from "./PlanRail";
import SteerBar from "./SteerBar";
import StepChip from "./StepChip";
import TurnRail from "./TurnRail";
import { readingLine, summaryForResult, titleForTool } from "./stepTitles";
import { useSmoothStream } from "./useSmoothStream";
import { useStickToBottom } from "./useStickToBottom";
import WeaveMark from "@/components/brand/WeaveMark";
import {
  IcoArrowDown,
  IcoChevronRight,
  IcoEdit,
  IcoMore,
  IcoRetry,
} from "@/components/ui/icons";

/* ------------------------------------------------------------------ history */

function fromHistory(messages: Message[], language: Language): ChatTurn[] {
  return messages.map((m) => {
    const text = language === "sw" ? m.content_sw : m.content_en;
    const artifacts = m.artifacts ?? [];

    /*
      Reloading a conversation must look like the conversation did.

      The server persists the whole step timeline (see `_step_timeline`), so the
      tool panels — what was searched, what was run, what each step produced —
      replay instead of vanishing on refresh. Steps come first, then the prose,
      then the artifacts: tool work precedes the answer it supports, which is
      the order the live stream produces for all but the rarest turn. Exact
      interleaving of prose and steps is not stored, and reconstructing it would
      mean persisting token offsets for a difference nobody can see.

      Entries written before this shape existed only carried `name`/`status`;
      those are skipped rather than rendered as blank chips.
    */
    const steps: Block[] = (m.tool_calls ?? [])
      .filter((c) => c && (c.id || c.title || c.tool))
      .map((c, i) => ({
        kind: "step" as const,
        id: c.id ?? `${m.id}-s${i}`,
        tool: c.tool ?? c.name,
        args: c.args,
        detail: c.detail,
        title: c.title || titleForTool(c.tool ?? c.name ?? "", c.args ?? {}, language),
        state: c.state === "error" ? ("error" as const) : ("done" as const),
        substeps: (c.substeps ?? []).map((s, j) => ({
          id: `${m.id}-s${i}-${j}`,
          text: s.text,
          url: s.url,
          detail: s.detail,
          state: "done" as const,
        })),
        artifacts: c.artifacts ?? [],
        pending: [],
        startedAt: Date.parse(m.created_at) || Date.now(),
        summary: c.summary,
        error: c.error,
      }));

    const blocks: Block[] =
      m.role === "assistant"
        ? [
            ...steps,
            { kind: "text", id: `${m.id}-t`, text },
            ...artifacts.map((a, i) => ({
              kind: "artifact" as const,
              id: `${m.id}-a${i}`,
              artifact: a,
            })),
          ]
        : [];
    return {
      id: m.id,
      role: m.role,
      text,
      blocks,
      thinking: "",
      citations: m.citations ?? [],
      images: m.images ?? [],
      artifacts,
      pending: false,
      // A plan the turn worked to is provenance, so it replays with the rest of
      // the transcript rather than existing only in the live stream.
      plan:
        m.plan && "steps" in m.plan && Array.isArray(m.plan.steps) && m.plan.steps.length
          ? (m.plan as Plan)
          : undefined,
      createdAt: Date.parse(m.created_at) || Date.now(),
    } satisfies ChatTurn;
  });
}

let uid = 0;
const nextId = (p: string) => `${p}-${Date.now().toString(36)}-${uid++}`;

/* --------------------------------------------------------------------- main */

export default function ChatClient({
  projectId,
  language,
  mode,
  initialMessages,
  datasets,
  services: initialServices = DEFAULT_SERVICES,
  effort: initialEffort = "weave",
  threadId,
  onThreadChange,
}: {
  projectId: string;
  language: Language;
  mode: string;
  initialMessages: Message[];
  datasets: Dataset[];
  lite?: boolean;
  services?: ServicePrefs;
  effort?: Effort;
  /** Which chat inside the project this view is showing. */
  threadId?: string;
  /** Called when the server rolls the conversation into a successor thread. */
  onThreadChange?: (id: string) => void;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>(() => fromHistory(initialMessages, language));
  const [input, setInput] = useState("");
  const [datasetId, setDatasetId] = useState<string>(datasets[0]?.id ?? "");
  const [streaming, setStreaming] = useState(false);
  const [effort, setEffort] = useState<Effort>(initialEffort);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [model, setModel] = useState<string>("");
  const [services, setServices] = useState<ServicePrefs>(initialServices);
  /** Set when the server summarised this chat and opened a successor. */
  const [rolled, setRolled] = useState<{ to: string; title: string } | null>(null);
  /**
   * The turn currently in flight, if it can be redirected. Comes from `meta`,
   * which the server sends before any tool runs — so steering is available from
   * the first second of a turn rather than only once tokens appear.
   */
  const [steerTurn, setSteerTurn] = useState<string | null>(null);
  /**
   * The dev server the assistant currently has running, if any.
   *
   * Held on the CLIENT rather than on a turn, because a server outlives the
   * turn that started it — the container keeps running between turns, which is
   * the whole point of it being persistent.
   */
  const [previewUrl, setPreviewUrl] = useState("");
  //: A transient explanation of why this turn behaved unusually — rate limited,
  //: answered by the offline fallback. Cleared when the next turn starts.
  const [notice, setNotice] = useState<string | null>(null);
  //: Whether an app has ever appeared this session. Used to auto-open the panel
  //: exactly once, so a user who closes it is not fighting us.
  const previewSeen = useRef(false);
  /** Transient message from the steering path ("noted for the next turn"). */
  const [steerNote, setSteerNote] = useState<string | null>(null);
  /** Set when history had to be trimmed to fit the model's window. */
  const [trimmed, setTrimmed] = useState(false);

  // right-hand panels (independent surfaces, several may be open)
  const dock = usePanelDock();
  // Pulled out so the callbacks below depend on a stable function rather than
  // on the dock object, which is a prop-identity dependency of every turn.
  const { openPanel } = dock;
  const [menuOpen, setMenuOpen] = useState(false);

  const [activeTurn, setActiveTurn] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const lastUserText = useRef("");
  /** Id of the step currently receiving substeps. */
  const activeStep = useRef<string | null>(null);
  const turnEls = useRef(new Map<string, HTMLElement>());
  /**
   * Artifacts already placed in the timeline.
   *
   * The backend emits each artifact twice by design — once LIVE from the tool
   * that produced it (so a chart appears the moment it exists, not twenty
   * minutes later when the run ends) and once in the end-of-turn summary that
   * history replays from. Without this the transcript shows every chart twice.
   */
  const seenArtifacts = useRef(new Set<string>());
  const threadRef = useRef<string | undefined>(threadId);
  threadRef.current = threadId;

  const scroller = useStickToBottom<HTMLDivElement>();

  /* ------------------------------------------------------------ model list */
  useEffect(() => {
    let alive = true;
    fetchCatalog().then((c) => {
      if (!alive) return;
      setCatalog(c);
      setModel((cur) => cur || c.currentModel);
    });
    return () => {
      alive = false;
    };
  }, []);

  // The window the meter is drawn against is the model's REAL context, resolved
  // by the server from the model itself — not a constant. Drawing against a
  // guess is worse than showing nothing, because the user trusts the gauge.
  const contextLimit = useMemo(
    () => (catalog ? contextFor(catalog, model) : 0),
    [catalog, model],
  );

  // A new chat starts clean: no carried-over artifacts, no stale rollover notice.
  useEffect(() => {
    seenArtifacts.current = new Set();
    setRolled(null);
    setTrimmed(false);
  }, [threadId]);

  /* --------------------------------------------------- block mutation utils */

  const patchLast = useCallback((fn: (t: ChatTurn) => ChatTurn) => {
    setTurns((prev) => {
      const next = [...prev];
      const i = next.length - 1;
      if (next[i]) next[i] = fn(next[i]);
      return next;
    });
  }, []);

  const patchBlocks = useCallback(
    (fn: (blocks: Block[]) => Block[]) => {
      patchLast((t) => ({ ...t, blocks: fn(t.blocks) }));
    },
    [patchLast],
  );

  /** Append streamed prose to the trailing text block, creating one if needed. */
  const appendText = useCallback(
    (chunk: string) => {
      if (!chunk) return;
      patchBlocks((blocks) => {
        const last = blocks[blocks.length - 1];
        if (last && isText(last)) {
          const copy = [...blocks];
          copy[copy.length - 1] = { ...last, text: last.text + chunk };
          return copy;
        }
        return [...blocks, { kind: "text", id: nextId("t"), text: chunk }];
      });
    },
    [patchBlocks],
  );

  const stream = useSmoothStream(appendText);

  // Keep the view pinned in the same commit that grew the content — BEFORE
  // paint. `useEffect` runs after the browser has already painted the taller
  // content, so at the exact bottom every token produced a one-frame up-jump
  // followed by a catch-up. `useLayoutEffect` closes that gap entirely.
  const keepPinned = scroller.keep;
  useLayoutEffect(() => {
    keepPinned();
  }, [turns, keepPinned]);

  /** Land a block at the end of the timeline, flushing buffered prose first. */
  const appendBlock = useCallback(
    (block: Block) => {
      // Structural boundary: buffered text belongs BEFORE this, not after it.
      const rest = stream.flushNow();
      if (rest) appendText(rest);
      patchBlocks((blocks) => [...blocks, block]);
    },
    [appendText, patchBlocks, stream],
  );

  /**
   * Place a generated artifact inline, where it was produced.
   *
   * Deduped by URL because the backend emits each artifact twice on purpose
   * (live from the tool, then again in the end-of-turn summary).
   */
  const addArtifact = useCallback(
    (a: Artifact) => {
      if (!a?.url || seenArtifacts.current.has(a.url)) return;
      seenArtifacts.current.add(a.url);
      appendBlock({ kind: "artifact", id: nextId("art"), artifact: a });
    },
    [appendBlock],
  );

  const mutateStep = useCallback(
    (id: string | null, fn: (s: StepBlock) => StepBlock) => {
      if (!id) return;
      patchBlocks((blocks) =>
        blocks.map((b) => (isStep(b) && b.id === id ? fn(b) : b)),
      );
    },
    [patchBlocks],
  );

  const startStep = useCallback(
    (opts: { id?: string; tool?: string; title: string; args?: Record<string, unknown> }) => {
      // Structural boundary: land any buffered prose FIRST so the step lands
      // after the text it followed, not in the middle of it.
      const rest = stream.flushNow();
      if (rest) appendText(rest);

      const id = opts.id ?? nextId("s");
      activeStep.current = id;
      patchBlocks((blocks) => [
        ...blocks,
        {
          kind: "step",
          id,
          tool: opts.tool,
          title: opts.title,
          args: opts.args,
          state: "running",
          substeps: [],
          artifacts: [],
          pending: [],
          startedAt: Date.now(),
        } satisfies StepBlock,
      ]);
      return id;
    },
    [appendText, patchBlocks, stream],
  );

  const ensureStep = useCallback(
    (fallbackTitle: string, tool?: string) =>
      activeStep.current ?? startStep({ title: fallbackTitle, tool }),
    [startStep],
  );

  const addSub = useCallback(
    (text: string, extra?: { url?: string; detail?: string; stepId?: string }) => {
      // Address the step EXPLICITLY when the server named one.
      //
      // Substeps used to attach to whichever step started most recently. That
      // is the same step while tools run one at a time, and the wrong one the
      // moment two run concurrently — the progress lines of one search would
      // appear underneath another. The server now stamps every tool event with
      // its own step id (see the orchestrator's `_scoped` emitter); falling
      // back to the most recent step keeps older servers working.
      const id = extra?.stepId ?? ensureStep(text);
      mutateStep(id, (s) => ({
        ...s,
        substeps: [
          // Close the previous substep when a new one starts.
          ...s.substeps.map((x) =>
            x.state === "running" ? { ...x, state: "done" as const } : x,
          ),
          { id: nextId("ss"), text, url: extra?.url, detail: extra?.detail, state: "running" },
        ],
      }));
    },
    [ensureStep, mutateStep],
  );

  const endStep = useCallback(
    (
      status: string,
      summary?: string,
      error?: string,
      detail?: string,
      stepId?: string,
    ) => {
      const id = stepId ?? activeStep.current;
      if (!id) return;
      const rest = stream.flushNow();
      if (rest) appendText(rest);
      mutateStep(id, (s) => ({
        ...s,
        state: status === "ok" || status === "success" ? "done" : "error",
        summary: summary || s.summary,
        error,
        detail: detail || s.detail,
        endedAt: Date.now(),
        substeps: s.substeps.map((x) =>
          x.state === "running" ? { ...x, state: "done" as const } : x,
        ),
      }));
      // Only clear the "most recent step" pointer if it is the step that just
      // ended. With concurrent tools an older step can finish last, and
      // blanking the pointer then would orphan the substeps of the one still
      // running.
      if (activeStep.current === id) activeStep.current = null;
    },
    [appendText, mutateStep, stream],
  );

  /* ---------------------------------------------------------------- actions */

  function stop() {
    abortRef.current?.abort();
  }

  // Clicking generated content in the transcript opens the panel that owns
  // that kind of artifact, rather than a generic viewer.
  const openArtifact = useCallback(
    (a: Artifact) => openPanel(categorise(a)),
    [openPanel],
  );

  async function regenerate() {
    if (streaming) return;
    setTurns((prev) => {
      const next = [...prev];
      if (next[next.length - 1]?.role === "assistant") next.pop();
      return [...next, blankAssistant()];
    });
    await runTurn(lastUserText.current, true);
  }

  async function editAndResend(userMsgId: string, newText: string) {
    if (streaming || !newText.trim()) return;
    try {
      await fetch(`/api/chat/${projectId}/from/${userMsgId}`, { method: "DELETE" });
    } catch {
      /* best effort — the resend below is the source of truth */
    }
    setTurns((prev) => {
      const idx = prev.findIndex((m) => m.id === userMsgId);
      return idx >= 0 ? prev.slice(0, idx) : prev;
    });
    await send(newText);
  }

  function blankAssistant(): ChatTurn {
    return {
      id: nextId("a"),
      role: "assistant",
      text: "",
      blocks: [],
      thinking: "",
      citations: [],
      images: [],
      artifacts: [],
      pending: true,
      createdAt: Date.now(),
    };
  }

  async function send(prompt?: string) {
    const content = (prompt ?? input).trim();
    if (!content || streaming) return;
    setInput("");
    lastUserText.current = content;
    setTurns((prev) => [
      ...prev,
      {
        id: nextId("u"),
        role: "user",
        text: content,
        blocks: [],
        thinking: "",
        citations: [],
        images: [],
        artifacts: [],
        pending: false,
        createdAt: Date.now(),
      },
      blankAssistant(),
    ]);
    await runTurn(content, false);
  }

  async function runTurn(content: string, regenerate: boolean) {
    setStreaming(true);
    setNotice(null);
    activeStep.current = null;
    scroller.pin();

    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const res = await fetch(`/api/chat/${projectId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ac.signal,
        body: JSON.stringify({
          content,
          language,
          dataset_id: datasetId || null,
          thread_id: threadRef.current ?? null,
          effort,
          model: model || null,
          regenerate,
          services,
        }),
      });
      if (!res.ok || !res.body) throw new Error(await res.text().catch(() => "request failed"));

      await consumeSse(res.body, (event, data) => {
        switch (event) {
          /* ---- structured step protocol (preferred) ---- */
          case "step_start":
            startStep({
              id: data.id,
              tool: data.tool,
              args: data.args,
              title: data.title || titleForTool(data.tool ?? "", data.args ?? {}, language),
            });
            break;
          case "step_note":
            // Model-authored title arriving after the deterministic one.
            mutateStep(data.id ?? activeStep.current, (s) => ({ ...s, title: data.title || s.title }));
            break;
          case "step_sub":
            addSub(data.text ?? "", {
              url: data.url,
              detail: data.detail,
              stepId: data.id,
            });
            break;
          case "step_end":
            endStep(data.status ?? "ok", data.summary, data.error, data.detail, data.id);
            break;

          /* ---- the supervised loop ---- */
          case "plan":
            patchLast((m) => ({
              ...m,
              plan: {
                goal: data.goal ?? "",
                steps: Array.isArray(data.steps) ? data.steps : [],
                checks: Array.isArray(data.checks) ? data.checks : [],
              },
            }));
            break;
          case "plan_step":
            patchLast((m) =>
              m.plan
                ? {
                    ...m,
                    plan: {
                      ...m.plan,
                      steps: m.plan.steps.map((s) =>
                        s.n === data.n
                          ? { ...s, status: data.status ?? s.status, note: data.note ?? s.note }
                          : s,
                      ),
                    },
                  }
                : m,
            );
            break;
          case "phase":
            patchLast((m) => ({ ...m, phase: String(data.name ?? "") }));
            break;

          /* ---- a dev server the assistant started ---- */
          case "preview": {
            const next = String(data.url ?? "");
            setPreviewUrl(next);
            // Open the panel the first time an app actually exists. Building
            // something runnable and leaving it behind a closed drawer is the
            // same as not running it, and after that the user's own choice to
            // close the panel is respected.
            if (next && !previewSeen.current) {
              previewSeen.current = true;
              dock.open.includes("preview") || dock.toggle("preview");
            }
            break;
          }
          case "continuing":
            // The model stopped early and is being sent back to finish. Say so
            // in the timeline: an unexplained second burst of work reads as the
            // assistant repeating itself.
            appendBlock({
              kind: "step",
              id: nextId("cont"),
              tool: "continue",
              title:
                language === "sw"
                  ? `Bado hakijakamilika — inaendelea (${(data.gaps ?? []).length})`
                  : `Not finished yet — continuing (${(data.gaps ?? []).length} outstanding)`,
              detail: (data.gaps ?? []).join("\n"),
              state: "done",
              substeps: [],
              artifacts: [],
              pending: [],
              startedAt: Date.now(),
            } satisfies StepBlock);
            break;
          case "review":
            appendBlock({
              kind: "step",
              id: nextId("rev"),
              tool: "review",
              title:
                data.verdict === "revise"
                  ? language === "sw"
                    ? `Ukaguzi umepata matatizo ${(data.defects ?? []).length}`
                    : `Review found ${(data.defects ?? []).length} problem(s)`
                  : language === "sw"
                    ? "Ukaguzi umepita"
                    : "Reviewed — no problems found",
              detail: (data.defects ?? []).join("\n"),
              state: data.verdict === "revise" ? "error" : "done",
              substeps: [],
              artifacts: [],
              pending: [],
              startedAt: Date.now(),
            } satisfies StepBlock);
            break;

          /* ---- artifact verification (opened in a real browser) ---- */
          case "verify_start":
            mutateStep(data.id ?? activeStep.current, (s) => ({
              ...s,
              verification: { state: "running" },
            }));
            break;
          case "verify_end":
            mutateStep(data.id ?? activeStep.current, (s) => ({
              ...s,
              verification: {
                state: data.checked ? (data.ok ? "ok" : "failed") : "ok",
                attempt: data.attempt,
                errors: data.errors ?? [],
                warnings: data.warnings ?? [],
                polish: data.polish ?? [],
                summary: data.summary ?? "",
              },
            }));
            break;

          /* ---- announced-but-not-yet-produced output ---- */
          case "artifact_pending":
            mutateStep(data.id ?? activeStep.current, (s) => ({
              ...s,
              pending: [
                ...s.pending,
                { id: data.id, kind: data.kind, tool: data.tool, title: data.title },
              ],
            }));
            break;
          case "artifact_pending_done":
            mutateStep(data.id ?? activeStep.current, (s) => ({
              ...s,
              pending: s.pending.map((p) =>
                p.id === data.id ? { ...p, resolved: true, failed: !data.ok } : p,
              ),
            }));
            break;

          /* ---- legacy events, mapped onto the same model ---- */
          case "tool_start":
            startStep({
              tool: data.name,
              args: data.input,
              title: data.title || titleForTool(data.name ?? "", data.input ?? {}, language),
            });
            break;
          case "tool_end":
            endStep(
              data.status ?? "ok",
              summaryForResult(data.name ?? "", data.result ?? {}, language),
            );
            break;
          case "searching":
            addSub((language === "sw" ? "Inatafuta: " : "Searching ") + (data.query ?? ""), {
              stepId: data.id,
            });
            break;
          case "search_results":
            addSub(
              language === "sw"
                ? `Matokeo ${data.count ?? 0}`
                : `Found ${data.count ?? 0} results`,
              { stepId: data.id },
            );
            break;
          case "fetching":
            addSub(readingLine(data.title ?? "", data.url ?? "", language), {
              url: data.url,
              stepId: data.id,
            });
            break;
          case "extracted":
            mutateStep(data.id ?? activeStep.current, (s) => ({
              ...s,
              substeps: s.substeps.map((x, i) =>
                i === s.substeps.length - 1 ? { ...x, state: "done" as const } : x,
              ),
            }));
            break;

          /* ---- content ---- */
          case "token":
            stream.push(data.text ?? "");
            break;
          case "thinking":
            patchLast((m) => ({ ...m, thinking: m.thinking + (data.text ?? "") }));
            break;
          case "meta":
            if (data.message_id) patchLast((m) => ({ ...m, id: data.message_id }));
            if (data.steerable && data.message_id) setSteerTurn(String(data.message_id));
            break;
          case "answer_start":
            // Any tool still open belongs to the phase before the answer.
            // Close every one of them, not just the most recent: with
            // concurrent tools there can legitimately be several running, and
            // leaving one spinning forever is how a finished turn keeps
            // pretending it is still working.
            patchBlocks((blocks) =>
              blocks.map((b) =>
                isStep(b) && b.state === "running"
                  ? {
                      ...b,
                      state: "done" as const,
                      endedAt: Date.now(),
                      substeps: b.substeps.map((x) =>
                        x.state === "running" ? { ...x, state: "done" as const } : x,
                      ),
                    }
                  : b,
              ),
            );
            activeStep.current = null;
            break;
          case "images":
            patchLast((m) => ({ ...m, images: data.images ?? [] }));
            break;
          case "artifact": {
            const a = data as Artifact;
            // Rendered inline in the timeline AND recorded on the step, so the
            // panel's grouped view still lists it.
            const owner = (data as { id?: string }).id ?? activeStep.current;
            if (owner) {
              mutateStep(owner, (s) => ({ ...s, artifacts: [...s.artifacts, a] }));
            }
            addArtifact(a);
            break;
          }
          case "citation":
            patchLast((m) => ({ ...m, citations: [...m.citations, data as Citation] }));
            break;

          /* ---- the assistant asking the user something ---- */
          case "ask_user": {
            const req: AskUserRequest = {
              id: String(data.id ?? ""),
              questions: Array.isArray(data.questions) ? data.questions : [],
            };
            if (req.id && req.questions.length) {
              appendBlock({ kind: "ask", id: nextId("ask"), request: req });
              // The turn is genuinely blocked on this, so make sure it is on
              // screen even if the user had scrolled up to read earlier work.
              scroller.pin("smooth");
            }
            break;
          }
          case "ask_user_done":
            // Answered here, in another tab, or timed out — collapse either way.
            patchBlocks((blocks) =>
              blocks.map((b) =>
                isAsk(b) && b.request.id === data.id
                  ? { ...b, request: { ...b.request, answered: true } }
                  : b,
              ),
            );
            break;

          /* ---- steering: the user redirected this turn mid-flight ---- */
          case "steer_applied":
            // Record it in the timeline so the transcript shows WHY the answer
            // changed direction. Without this the restart below looks like a
            // glitch rather than the model doing as it was told.
            patchBlocks((blocks) => [
              ...blocks,
              {
                kind: "step",
                id: nextId("steer"),
                tool: "steer",
                title:
                  (language === "sw" ? "Umeelekeza upya: " : "You redirected: ") +
                  String(data.text ?? ""),
                state: "done",
                substeps: [],
                artifacts: [],
                pending: [],
                startedAt: Date.now(),
                summary:
                  typeof data.restarts_left === "number"
                    ? language === "sw"
                      ? `mabadiliko ${data.restarts_left} yamebaki`
                      : `${data.restarts_left} redirects left`
                    : undefined,
              } satisfies StepBlock,
            ]);
            setSteerNote(null);
            break;
          case "answer_restart":
            // Everything streamed so far was reasoning the user has overridden.
            // Drop the in-flight text block so what is on screen matches what
            // the model actually reasoned about.
            stream.reset();
            patchBlocks((blocks) => {
              const out = [...blocks];
              while (out.length && out[out.length - 1].kind === "text") out.pop();
              return out;
            });
            patchLast((m) => ({ ...m, text: "" }));
            break;
          case "steer_deferred":
            setSteerNote(
              language === "sw"
                ? "Maelekezo yamehifadhiwa kwa zamu ijayo."
                : "Noted — I'll pick that up on the next turn.",
            );
            break;

          /* ---- something the user needs to know about this turn ---- */
          case "notice":
            // Rate limits and fallbacks. Surfaced in the timeline rather than
            // as a toast: it explains the shape of THIS answer, so it has to
            // stay attached to it when the transcript is read back later.
            setNotice(String(data.text ?? ""));
            break;

          /* ---- context lifecycle ---- */
          case "context_trimmed":
            // Say it out loud. Silently dropping the start of a conversation is
            // how an assistant appears to "forget" with no signal to the reader.
            setTrimmed(true);
            break;
          case "summarizing":
            addSub(
              language === "sw"
                ? "Inafupisha mazungumzo…"
                : "Summarising this chat…",
            );
            break;
          case "thread_rolled":
            setRolled({ to: String(data.to ?? ""), title: String(data.title ?? "") });
            break;

          case "done":
            // The server rolls to a successor thread when this one filled the
            // model's window; follow it, or the next turn would be written into
            // a chat the model can no longer read in full.
            if (data.next_thread_id && onThreadChange) {
              onThreadChange(String(data.next_thread_id));
            }
            break;
          case "error":
            patchLast((m) => ({ ...m, pending: false, error: true }));
            appendText(`\n\n⚠ ${data.message ?? "error"}`);
            break;
          default:
            break;
        }
      });

      // Let the smoother land the tail naturally rather than dumping it.
      stream.finish();
      await waitFor(() => stream.pending() === 0, 4000);
    } catch (err) {
      const aborted = (err as Error).name === "AbortError";
      const rest = stream.flushNow();
      if (rest) appendText(rest);
      if (!aborted) {
        patchLast((m) => ({ ...m, error: true }));
        appendText(`\n\n⚠ ${(err as Error).message}`);
      }
    } finally {
      // Close every step still marked running, not only the most recent one:
      // a turn can end with several concurrent tools open (or with one left
      // open by an aborted stream), and a chip that spins forever is the
      // clearest possible way to tell the user a finished turn is still going.
      patchBlocks((blocks) =>
        blocks.map((b) =>
          isStep(b) && b.state === "running"
            ? {
                ...b,
                state: "done" as const,
                endedAt: Date.now(),
                substeps: b.substeps.map((x) =>
                  x.state === "running" ? { ...x, state: "done" as const } : x,
                ),
              }
            : b,
        ),
      );
      activeStep.current = null;
      const rest = stream.flushNow();
      if (rest) appendText(rest);
      patchLast((m) => ({ ...m, pending: false, phase: undefined }));
      abortRef.current = null;
      setStreaming(false);
      // The turn is over, so there is nothing left to redirect.
      setSteerTurn(null);
      setSteerNote(null);
    }
  }

  /**
   * Redirect the turn that is still running.
   *
   * Fire-and-forget by design: the visible result is the `steer_applied` and
   * `answer_restart` events coming back down the stream, and blocking the input
   * on the POST would make the interaction feel slower than it is. A 404 means
   * the turn finished between the keypress and the request — the honest thing to
   * say is that it was too late, not to invent a queue for it.
   */
  const sendSteer = useCallback(
    async (text: string, kind = "redirect") => {
      const turn = steerTurn;
      if (!turn || !text.trim()) return;
      setSteerNote(language === "sw" ? "Inatuma…" : "Sending…");
      try {
        const res = await fetch(`/api/steer/${turn}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, kind }),
        });
        if (!res.ok) {
          setSteerNote(
            language === "sw"
              ? "Umechelewa — zamu imekwisha."
              : "Too late — that turn already finished.",
          );
          return;
        }
        setSteerNote(null);
      } catch {
        setSteerNote(language === "sw" ? "Imeshindikana." : "Could not send that.");
      }
    },
    [steerTurn, language],
  );

  /* ------------------------------------------------------------ derived UI */

  /*
    EVERYTHING BELOW IS DERIVED FROM THE WHOLE TRANSCRIPT, AND NONE OF IT IS
    URGENT.

    `payload`, `counts`, `railTurns` and `contextUsed` each walk every turn in
    the conversation. Computed from `turns` directly they ran on every streamed
    chunk — sixty times a second, over a transcript that only grows — to update
    a panel badge, a rail label and a context gauge, none of which anyone reads
    while text is arriving. On a long chat that is the single largest per-token
    cost in this component, and it is spent on the least important pixels.

    `useDeferredValue` lets React render the growing text at normal priority and
    recompute these once the burst settles. The numbers lag by a frame or two
    during a stream and are exact the moment it stops, which is the correct
    trade for a badge.
  */
  const settledTurns = useDeferredValue(turns);

  const payload = useMemo(
    () => ({
      previewUrl,
      artifacts: settledTurns.flatMap(turnArtifacts),
      images: settledTurns.flatMap((t) => t.images) as WebImage[],
      citations: settledTurns.flatMap((t) => t.citations) as Citation[],
      datasets,
      // The canvas panel loads its own document rather than reading from the
      // turn stream, so it needs the project it belongs to.
      projectId,
    }),
    [settledTurns, datasets, projectId, previewUrl],
  );

  const counts = useMemo(() => panelCounts(payload), [payload]);
  const totalArtifacts = Object.values(counts).reduce((a, b) => a + b, 0);

  // Same chars/token ratio the server budgets with, so the gauge and the actual
  // trimming decision never disagree.
  const contextUsed = useMemo(() => {
    const chars = settledTurns.reduce((n, t) => n + turnText(t).length, 0);
    return Math.ceil(chars / 3.6);
  }, [settledTurns]);

  const markAnswered = useCallback((id: string) => {
    setTurns((prev) =>
      prev.map((t) => ({
        ...t,
        blocks: t.blocks.map((b) =>
          isAsk(b) && b.request.id === id
            ? { ...b, request: { ...b.request, answered: true } }
            : b,
        ),
      })),
    );
  }, []);

  const railTurns = useMemo(
    () =>
      settledTurns.map((t) => ({
        id: t.id,
        role: t.role,
        label: (turnText(t) || "…").slice(0, 90),
      })),
    [settledTurns],
  );

  // Track which turn is in view for the rail.
  useEffect(() => {
    const root = scroller.ref.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) setActiveTurn((visible.target as HTMLElement).dataset.turnId ?? null);
      },
      { root, rootMargin: "-10% 0px -70% 0px", threshold: 0 },
    );
    for (const el of turnEls.current.values()) io.observe(el);
    return () => io.disconnect();
  }, [turns.length, scroller.ref]);

  const registerTurn = useCallback((id: string, el: HTMLElement | null) => {
    if (el) turnEls.current.set(id, el);
    else turnEls.current.delete(id);
  }, []);

  const jumpTo = useCallback((id: string) => {
    turnEls.current.get(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const empty = turns.length === 0;

  return (
    <div className="relative flex h-full min-w-0 overflow-hidden">
      {/* ------------------------------------------------- conversation column */}
      {/*
        DESKTOP: the transcript keeps a hard floor (basis 380 + shrink-0) so the
        panels squeeze and the conversation does not.

        MOBILE: those same two classes were the "chat overflows on the right"
        bug — `flex-basis: 380px` with `flex-shrink: 0` cannot shrink below
        380px, so on a 360px phone the column stuck out past the viewport and
        took the whole page with it. Below `lg` the column is simply
        `flex-1 min-w-0`, which is what lets a wide code block or table scroll
        inside itself instead of widening the page.
      */}
      <div className="relative flex min-w-0 flex-1 flex-col lg:shrink-0 lg:basis-[380px]">
        {/* thread menu */}
        {/* On the shared floating rail — see --float-top / --float-h. This used
            to be `top-2` with no safe-area allowance, so on a notched phone it
            sat higher than the other two controls and, at the extreme, under
            the status bar. */}
        <div
          className="pointer-events-none absolute right-2 z-30 flex items-center"
          style={{ top: "var(--float-top)", height: "var(--float-h)" }}
        >
          <div className="pointer-events-auto relative">
            <button
              onClick={() => setMenuOpen((v) => !v)}
              aria-label={language === "sw" ? "Chaguo za mazungumzo" : "Thread options"}
              aria-expanded={menuOpen}
              className="relative grid h-8 w-8 place-items-center rounded-full text-fg-faint backdrop-blur transition-colors duration-fast hover:bg-surface-hover hover:text-fg"
            >
              <IcoMore size={17} />
              {totalArtifacts > 0 && dock.open.length === 0 && (
                <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-accent" />
              )}
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
                <div className="animate-rise absolute right-0 top-full z-50 mt-1 w-60 overflow-hidden border border-border bg-surface shadow-lg">
                  <div className="eyebrow border-b border-border px-3 py-2">
                    {language === "sw" ? "Yaliyoundwa" : "Generated in this thread"}
                  </div>
                  {PANEL_ORDER.map((pid) => {
                    const meta = PANEL_META[pid];
                    const Icon = meta.icon;
                    const n = counts[pid];
                    const isOpen = dock.open.includes(pid);
                    return (
                      <button
                        key={pid}
                        onClick={() => {
                          dock.toggle(pid);
                          setMenuOpen(false);
                        }}
                        className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors duration-fast hover:bg-surface-hover ${
                          isOpen ? "bg-accent-soft" : ""
                        }`}
                      >
                        <Icon size={15} className={n ? "text-accent" : "text-fg-faint"} />
                        <span className="flex-1 text-fg">
                          {language === "sw" ? meta.label[0] : meta.label[1]}
                        </span>
                        <span className="font-mono text-[11px] text-fg-faint">{n || "—"}</span>
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>

        <div
          ref={scroller.ref}
          onScroll={scroller.onScroll}
          className="transcript min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden"
        >
          {/*
            Bottom padding clears the composer, which is an overlay: it must
            account for the composer's own height, the safe area, and the
            keyboard inset, or the last line of an answer sits under the input.
          */}
          <div
            className="pad-chrome-top mx-auto w-full min-w-0 max-w-chat px-4"
            /*
              Cleared against the composer's MEASURED height (published as
              --composer-h, which already includes the safe area and any bar
              stacked above the input), not a constant. The constant was 11rem,
              correct only for a one-line input.
            */
            style={{
              paddingBottom:
                "calc(var(--composer-h, 9.5rem) + 1.75rem + var(--kb-inset))",
            }}
          >
            {empty && <EmptyState language={language} mode={mode} />}
            {turns.map((turn, i) =>
              turn.role === "user" ? (
                <UserTurn
                  key={turn.id}
                  turn={turn}
                  language={language}
                  register={registerTurn}
                  onEdit={
                    turn.id.startsWith("u-") ? undefined : (nt) => editAndResend(turn.id, nt)
                  }
                />
              ) : (
                <AssistantTurn
                  key={turn.id}
                  turn={turn}
                  language={language}
                  register={registerTurn}
                  streaming={streaming && i === turns.length - 1}
                  onOpenArtifact={openArtifact}
                  onAnswered={markAnswered}
                  onRegenerate={
                    !streaming && i === turns.length - 1 && !turn.pending ? regenerate : undefined
                  }
                />
              ),
            )}

            {notice && <Notice tone="warn" text={notice} />}

            {trimmed && !rolled && (
              <Notice
                tone="warn"
                text={
                  language === "sw"
                    ? "Mazungumzo haya yamekuwa marefu kuliko dirisha la modeli, hivyo sehemu ya mwanzo haikutumwa. Kumbukumbu ya mradi bado inatumika."
                    : "This chat is longer than the model's context window, so the earliest turns weren't sent. Project memory still applies."
                }
              />
            )}

            {rolled && (
              <Notice
                tone="accent"
                text={
                  language === "sw"
                    ? `Mazungumzo yamefikia kikomo cha muktadha. Nimeyafupisha na kufungua "${rolled.title}" ukiendelea nayo.`
                    : `This chat reached the model's context limit. It has been summarised and continued in "${rolled.title}".`
                }
                action={
                  onThreadChange && rolled.to
                    ? {
                        label: language === "sw" ? "Nenda huko" : "Go there",
                        onClick: () => onThreadChange(rolled.to),
                      }
                    : undefined
                }
              />
            )}
          </div>
        </div>

        <TurnRail
          turns={railTurns}
          activeId={activeTurn}
          onJump={jumpTo}
          language={language}
        />

        {/* scroll to bottom — only when detached */}
        <button
          onClick={() => scroller.pin("smooth")}
          aria-label={language === "sw" ? "Nenda chini" : "Scroll to bottom"}
          /* Rides above the composer, so it tracks both the keyboard and a
             composer that has grown (a long draft, the steering bar). */
          style={{ bottom: "calc(var(--composer-h, 9.5rem) + 0.6rem + var(--kb-inset))" }}
          className={`absolute left-1/2 z-30 grid h-9 w-9 -translate-x-1/2 place-items-center rounded-full border border-border bg-surface text-fg-muted shadow-soft transition-all duration-slow ease-expo hover:border-accent-line hover:text-fg ${
            scroller.pinned
              ? "pointer-events-none translate-y-3 scale-90 opacity-0"
              : "translate-y-0 scale-100 opacity-100"
          }`}
        >
          <IcoArrowDown size={16} />
        </button>

        <Composer
          /*
            Both of these are handed to the composer rather than rendered beside
            it. As siblings they sat in normal flow at the bottom of this
            column, underneath an absolutely-positioned composer at the same
            coordinates — so the bar for redirecting a running turn and the
            entry point to voice and screen sharing were both painted over and
            unreachable. Inside the overlay they are visible, they sit exactly
            where the user's hands already are, and their height is included in
            the measurement the transcript pads against.
          */
          above={
            streaming && steerTurn ? (
              <SteerBar language={language} note={steerNote} onSteer={sendSteer} />
            ) : !streaming ? (
              <LiveBar projectId={projectId} language={language} />
            ) : null
          }
          input={input}
          setInput={setInput}
          onSend={() => send()}
          onStop={stop}
          streaming={streaming}
          language={language}
          datasets={datasets}
          datasetId={datasetId}
          setDatasetId={setDatasetId}
          effort={effort}
          setEffort={setEffort}
          models={catalog?.models ?? []}
          model={model}
          setModel={setModel}
          services={services}
          setServices={setServices}
          contextUsed={contextUsed}
          contextLimit={contextLimit}
        />
      </div>

      {/* ------------------------------------ independent right-hand panels */}
      <PanelDock
        open={dock.open}
        data={payload}
        language={language}
        onClose={dock.closePanel}
        onCloseAll={dock.closeAll}
      />
    </div>
  );
}

/* -------------------------------------------------------------------- turns */

/*
  MEMOISED, AND THE REASON MATTERS.

  `patchLast` copies the turns array but replaces only the last element, so
  every earlier turn keeps its object identity across a streamed chunk. With
  these components memoised, a token therefore re-renders exactly one turn
  instead of the entire conversation — which is what makes the text arrive
  smoothly in a chat that has been going for an hour rather than progressively
  more slowly.

  This only holds while the props are stable. `onOpenArtifact`, `onAnswered`
  and `register` are all `useCallback`s over stable dependencies; if you add a
  prop here, give it the same treatment or you have quietly turned memoisation
  off for the whole transcript.
*/
const UserTurn = memo(function UserTurn({
  turn,
  language,
  onEdit,
  register,
}: {
  turn: ChatTurn;
  language: Language;
  onEdit?: (t: string) => void;
  register: (id: string, el: HTMLElement | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(turn.text);

  return (
    <div
      ref={(el) => register(turn.id, el)}
      data-turn-id={turn.id}
      className="group animate-rise mb-3 mt-12 first:mt-0"
    >
      <div className="mb-1.5 flex items-center gap-2">
        <span className="eyebrow">{language === "sw" ? "Wewe" : "You"}</span>
        <span className="h-px flex-1 bg-border" />
        {onEdit && !editing && (
          <button
            onClick={() => {
              setVal(turn.text);
              setEditing(true);
            }}
            className="flex items-center gap-1 text-[11px] text-fg-faint opacity-0 transition-all duration-fast hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"
          >
            <IcoEdit size={11} />
            {language === "sw" ? "Hariri" : "Edit"}
          </button>
        )}
      </div>

      {editing ? (
        <div>
          <textarea
            value={val}
            onChange={(e) => setVal(e.target.value)}
            rows={3}
            className="w-full resize-none border border-border bg-surface px-3 py-2 font-read text-[16px] outline-none transition-colors duration-fast focus:border-accent-line"
          />
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => {
                setEditing(false);
                onEdit?.(val);
              }}
              className="bg-fg px-3 py-1.5 text-[11px] uppercase tracking-widest text-bg transition-opacity duration-fast hover:opacity-85"
            >
              {language === "sw" ? "Tuma" : "Send"}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-1.5 text-[11px] uppercase tracking-widest text-fg-muted transition-colors duration-fast hover:text-fg"
            >
              {language === "sw" ? "Ghairi" : "Cancel"}
            </button>
          </div>
        </div>
      ) : (
        <div className="whitespace-pre-wrap border-l-2 border-accent pl-3 font-read text-[17px] leading-relaxed text-fg">
          {turn.text}
        </div>
      )}
    </div>
  );
});

const AssistantTurn = memo(function AssistantTurn({
  turn,
  language,
  streaming,
  onRegenerate,
  onOpenArtifact,
  onAnswered,
  register,
}: {
  turn: ChatTurn;
  language: Language;
  streaming: boolean;
  onRegenerate?: () => void;
  onOpenArtifact: (a: Artifact) => void;
  onAnswered: (id: string) => void;
  register: (id: string, el: HTMLElement | null) => void;
}) {
  const nothingYet = turn.blocks.length === 0 && !turn.thinking;

  return (
    <div ref={(el) => register(turn.id, el)} data-turn-id={turn.id} className="animate-rise mb-2">
      {turn.plan && (
        <PlanRail plan={turn.plan} language={language} live={turn.pending} />
      )}

      {turn.thinking && <Reasoning text={turn.thinking} active={turn.pending} language={language} />}

      {/* The block timeline: prose, work, questions and generated output,
          interleaved in the order they actually happened. */}
      {turn.blocks.map((b, i) => {
        if (isText(b)) {
          return b.text.trim() ? (
            <Markdown
              key={b.id}
              text={b.text}
              streaming={streaming && i === turn.blocks.length - 1}
              onOpenArtifact={onOpenArtifact}
            />
          ) : null;
        }
        if (isAsk(b)) {
          return (
            <AskUserCard
              key={b.id}
              request={b.request}
              language={language}
              onAnswered={onAnswered}
            />
          );
        }
        if (isArtifactBlock(b)) {
          return (
            <InlineArtifact
              key={b.id}
              artifact={b.artifact}
              language={language}
              onOpen={onOpenArtifact}
            />
          );
        }
        return <StepChip key={b.id} step={b} language={language} onOpenArtifact={onOpenArtifact} />;
      })}

      {/* No prebuilt loader. Just an honest, unbounded presence indicator that
          says "still here" without implying a duration. */}
      {turn.pending && (nothingYet || turn.phase === "planning" || turn.phase === "reviewing") && (
        <div className="flex items-center gap-2 py-1">
          <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />
          <span className="h-px w-8 bg-border" />
          {turn.phase && (
            <span className="text-2xs uppercase tracking-widest text-fg-faint">
              {phaseLabel(turn.phase, language)}
            </span>
          )}
        </div>
      )}

      {turn.citations.length > 0 && <Sources citations={turn.citations} language={language} />}

      {onRegenerate && (
        <button
          onClick={onRegenerate}
          className="mt-4 inline-flex items-center gap-1.5 border border-border px-2.5 py-1 text-[11px] uppercase tracking-widest text-fg-muted transition-all duration-fast ease-soft hover:border-border-mid hover:text-fg"
        >
          <IcoRetry size={12} />
          {language === "sw" ? "Zalisha upya" : "Regenerate"}
        </button>
      )}
    </div>
  );
});

/**
 * What the supervisor is doing between bursts of visible work.
 *
 * Planning and reviewing are model calls whose output is deliberately NOT
 * streamed — they are scaffolding, not the answer. Without a label the reader
 * sees ten silent seconds and concludes the thing has hung.
 */
function phaseLabel(phase: string, language: Language): string {
  const sw: Record<string, string> = {
    planning: "inapanga",
    working: "inafanya kazi",
    reviewing: "inakagua kazi",
    repairing: "inarekebisha",
  };
  const en: Record<string, string> = {
    planning: "planning",
    working: "working",
    reviewing: "checking its work",
    repairing: "fixing what the check found",
  };
  return (language === "sw" ? sw : en)[phase] ?? phase;
}

function Reasoning({
  text,
  active,
  language,
}: {
  text: string;
  active: boolean;
  language: Language;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-3 border-l-2 border-border pl-3">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 py-0.5 text-left"
      >
        <IcoChevronRight size={13} className="chev text-fg-faint" data-open={open} />
        <span className={`text-[13px] ${active ? "shimmer font-medium" : "text-fg-muted"}`}>
          {language === "sw" ? "Mawazo" : "Reasoning"}
        </span>
      </button>
      <div className="wv-collapse" data-open={open}>
        <div className="wv-collapse-inner">
          <div className="whitespace-pre-wrap py-1.5 font-read text-[13px] italic leading-relaxed text-fg-muted">
            {text}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * A quiet, full-width status line inside the transcript.
 *
 * Used for things the SYSTEM did that change what the assistant can see —
 * history being trimmed, a chat being rolled into a successor. These have to be
 * visible: an assistant that has silently lost the start of the conversation
 * looks like it is being careless rather than out of room.
 */
function Notice({
  tone,
  text,
  action,
}: {
  tone: "warn" | "accent";
  text: string;
  action?: { label: string; onClick: () => void };
}) {
  const border = tone === "warn" ? "border-warn" : "border-accent";
  const fg = tone === "warn" ? "text-warn" : "text-accent";
  return (
    <div className={`animate-rise my-4 border-l-2 ${border} pl-3`}>
      <p className="text-[13px] leading-relaxed text-fg-muted">{text}</p>
      {action && (
        <button
          onClick={action.onClick}
          className={`mt-1.5 text-[12px] uppercase tracking-widest ${fg} transition-opacity duration-fast hover:opacity-70`}
        >
          {action.label} →
        </button>
      )}
    </div>
  );
}

function Sources({ citations, language }: { citations: Citation[]; language: Language }) {
  return (
    <div className="mt-5 border-t border-border pt-3">
      <div className="eyebrow mb-2">{language === "sw" ? "Vyanzo" : "Sources"}</div>
      <div className="flex flex-wrap gap-1.5">
        {citations.map((c, i) => {
          const inner = (
            <span className="inline-flex items-center gap-1.5 border border-border bg-surface px-2 py-1 text-[11px] text-fg-muted transition-colors duration-fast hover:border-accent-line hover:text-fg">
              <span className="font-mono text-[10px] text-fg-faint">{i + 1}</span>
              <span className="max-w-[15rem] truncate">{c.title || c.url}</span>
              {c.access_status === "paywalled" && (
                <span className="bg-warn-soft px-1 text-[9.5px] text-warn">
                  {language === "sw" ? "malipo" : "paywalled"}
                </span>
              )}
              {c.predatory_flag && (
                <span className="bg-danger-soft px-1 text-[9.5px] text-danger">
                  {language === "sw" ? "shaka" : "caution"}
                </span>
              )}
            </span>
          );
          return c.url ? (
            <a key={i} href={c.url} target="_blank" rel="noreferrer">
              {inner}
            </a>
          ) : (
            <span key={i}>{inner}</span>
          );
        })}
      </div>
    </div>
  );
}

function EmptyState({ language, mode }: { language: Language; mode: string }) {
  return (
    <div className="flex min-h-[52vh] flex-col items-center justify-center text-center">
      <WeaveMark size="lg" className="text-fg" duration={2600} />
      <p className="mt-6 max-w-sm font-read text-[15px] italic leading-relaxed text-fg-muted">
        {mode === "researcher"
          ? language === "sw"
            ? "Hali ya mtafiti — majibu ya moja kwa moja yenye rejea."
            : "Researcher mode — direct answers, strictly cited."
          : language === "sw"
            ? "Hali ya mwanafunzi — mwongozo hatua kwa hatua."
            : "Student mode — guided, step by step."}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------- transport */

function waitFor(pred: () => boolean, timeoutMs: number): Promise<void> {
  return new Promise((resolve) => {
    const started = Date.now();
    const check = () => {
      if (pred() || Date.now() - started > timeoutMs) return resolve();
      requestAnimationFrame(check);
    };
    check();
  });
}

async function consumeSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: any) => void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let event = "message";
      let dataLine = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
      }
      if (!dataLine) continue;
      try {
        onEvent(event, JSON.parse(dataLine));
      } catch {
        /* a malformed frame must not kill the stream */
      }
    }
  }
}
