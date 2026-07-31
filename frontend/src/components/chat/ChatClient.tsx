"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type {
  Artifact,
  Citation,
  Dataset,
  Effort,
  Language,
  Message,
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
  /** Transient message from the steering path ("noted for the next turn"). */
  const [steerNote, setSteerNote] = useState<string | null>(null);
  /** Set when history had to be trimmed to fit the model's window. */
  const [trimmed, setTrimmed] = useState(false);

  // right-hand panels (independent surfaces, several may be open)
  const dock = usePanelDock();
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
  useLayoutEffect(() => {
    scroller.keep();
  }, [turns, scroller]);

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
    (text: string, extra?: { url?: string; detail?: string }) => {
      const id = ensureStep(text);
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
    (status: string, summary?: string, error?: string, detail?: string) => {
      const id = activeStep.current;
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
      activeStep.current = null;
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
    (a: Artifact) => dock.openPanel(categorise(a)),
    [dock],
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
            addSub(data.text ?? "", { url: data.url, detail: data.detail });
            break;
          case "step_end":
            endStep(data.status ?? "ok", data.summary, data.error, data.detail);
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
            addSub(
              (language === "sw" ? "Inatafuta: " : "Searching ") + (data.query ?? ""),
            );
            break;
          case "search_results":
            addSub(
              language === "sw"
                ? `Matokeo ${data.count ?? 0}`
                : `Found ${data.count ?? 0} results`,
            );
            break;
          case "fetching":
            addSub(readingLine(data.title ?? "", data.url ?? "", language), { url: data.url });
            break;
          case "extracted":
            mutateStep(activeStep.current, (s) => ({
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
            if (activeStep.current) endStep("ok");
            break;
          case "images":
            patchLast((m) => ({ ...m, images: data.images ?? [] }));
            break;
          case "artifact": {
            const a = data as Artifact;
            // Rendered inline in the timeline AND recorded on the step, so the
            // panel's grouped view still lists it.
            if (activeStep.current) {
              mutateStep(activeStep.current, (s) => ({ ...s, artifacts: [...s.artifacts, a] }));
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
      if (activeStep.current) endStep("ok");
      const rest = stream.flushNow();
      if (rest) appendText(rest);
      patchLast((m) => ({ ...m, pending: false }));
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

  const payload = useMemo(
    () => ({
      artifacts: turns.flatMap(turnArtifacts),
      images: turns.flatMap((t) => t.images) as WebImage[],
      citations: turns.flatMap((t) => t.citations) as Citation[],
      datasets,
      // The canvas panel loads its own document rather than reading from the
      // turn stream, so it needs the project it belongs to.
      projectId,
    }),
    [turns, datasets, projectId],
  );

  const counts = useMemo(() => panelCounts(payload), [payload]);
  const totalArtifacts = Object.values(counts).reduce((a, b) => a + b, 0);

  // Same chars/token ratio the server budgets with, so the gauge and the actual
  // trimming decision never disagree.
  const contextUsed = useMemo(() => {
    const chars = turns.reduce((n, t) => n + turnText(t).length, 0);
    return Math.ceil(chars / 3.6);
  }, [turns]);

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
      turns.map((t) => ({
        id: t.id,
        role: t.role,
        label: (turnText(t) || "…").slice(0, 90),
      })),
    [turns],
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
            style={{ paddingBottom: "calc(11rem + var(--safe-bottom) + var(--kb-inset))" }}
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
          /* Rides above the composer, so it tracks the keyboard too. */
          style={{ bottom: "calc(8rem + var(--safe-bottom) + var(--kb-inset))" }}
          className={`absolute left-1/2 z-30 grid h-9 w-9 -translate-x-1/2 place-items-center rounded-full border border-border bg-surface text-fg-muted shadow-soft transition-all duration-slow ease-expo hover:border-accent-line hover:text-fg ${
            scroller.pinned
              ? "pointer-events-none translate-y-3 scale-90 opacity-0"
              : "translate-y-0 scale-100 opacity-100"
          }`}
        >
          <IcoArrowDown size={16} />
        </button>

        {/* Redirect the model while it is still working. Only while a turn is
            live, and directly above the composer — where the user's hands
            already are when they see it going the wrong way. */}
        {streaming && steerTurn && (
          <SteerBar language={language} note={steerNote} onSteer={sendSteer} />
        )}

        {/* Live voice, ambient listening and screen sharing. Collapsed to a
            single button until started — a chat that permanently shows
            microphone controls implies the microphone is already doing
            something. */}
        {!streaming && <LiveBar projectId={projectId} language={language} />}

        <Composer
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

function UserTurn({
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
}

function AssistantTurn({
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
      {turn.pending && nothingYet && (
        <div className="flex items-center gap-2 py-1">
          <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />
          <span className="h-px w-8 bg-border" />
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
