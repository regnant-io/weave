"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import type { Block, ChatTurn, StepBlock } from "@/lib/chatTypes";
import { isStep, isText, turnArtifacts, turnText } from "@/lib/chatTypes";
import PanelDock, { usePanelDock } from "./panels/PanelDock";
import { categorise, PANEL_META, PANEL_ORDER, panelCounts, type PanelId } from "./panels/panels";
import Composer, { type ModelInfo } from "./Composer";
import Markdown from "./Markdown";
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
    return {
      id: m.id,
      role: m.role,
      text,
      blocks: m.role === "assistant" ? [{ kind: "text", id: `${m.id}-t`, text }] : [],
      thinking: "",
      citations: m.citations ?? [],
      images: m.images ?? [],
      artifacts: m.artifacts ?? [],
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
}: {
  projectId: string;
  language: Language;
  mode: string;
  initialMessages: Message[];
  datasets: Dataset[];
  lite?: boolean;
  services?: ServicePrefs;
  effort?: Effort;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>(() => fromHistory(initialMessages, language));
  const [input, setInput] = useState("");
  const [datasetId, setDatasetId] = useState<string>(datasets[0]?.id ?? "");
  const [streaming, setStreaming] = useState(false);
  const [effort, setEffort] = useState<Effort>(initialEffort);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState<string>("");
  const [services, setServices] = useState<ServicePrefs>(initialServices);

  // right-hand panels (independent surfaces, several may be open)
  const dock = usePanelDock();
  const [menuOpen, setMenuOpen] = useState(false);

  const [activeTurn, setActiveTurn] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const lastUserText = useRef("");
  /** Id of the step currently receiving substeps. */
  const activeStep = useRef<string | null>(null);
  const turnEls = useRef(new Map<string, HTMLElement>());

  const scroller = useStickToBottom<HTMLDivElement>();

  /* ------------------------------------------------------------ model list */
  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((d) => {
        // Tolerate both the legacy string[] shape and the richer object shape.
        const raw = d.models ?? [];
        const list: ModelInfo[] = raw.map((m: any) =>
          typeof m === "string" ? { name: m } : { name: m.name, context: m.context },
        );
        setModels(list);
        setModel(d.current_model ?? list[0]?.name ?? "");
      })
      .catch(() => {});
  }, []);

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

  // Keep the view pinned in the same commit that grew the content — before
  // paint, so no intermediate unpinned frame is ever shown.
  useEffect(() => {
    scroller.keep();
  }, [turns, scroller]);

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
            if (activeStep.current) {
              mutateStep(activeStep.current, (s) => ({ ...s, artifacts: [...s.artifacts, a] }));
            } else {
              patchLast((m) => ({ ...m, artifacts: [...m.artifacts, a] }));
            }
            break;
          }
          case "citation":
            patchLast((m) => ({ ...m, citations: [...m.citations, data as Citation] }));
            break;
          case "done":
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
    }
  }

  /* ------------------------------------------------------------ derived UI */

  const payload = useMemo(
    () => ({
      artifacts: turns.flatMap(turnArtifacts),
      images: turns.flatMap((t) => t.images) as WebImage[],
      citations: turns.flatMap((t) => t.citations) as Citation[],
      datasets,
    }),
    [turns, datasets],
  );

  const counts = useMemo(() => panelCounts(payload), [payload]);
  const totalArtifacts = Object.values(counts).reduce((a, b) => a + b, 0);

  const contextUsed = useMemo(() => {
    const chars = turns.reduce((n, t) => n + turnText(t).length, 0);
    return Math.ceil(chars / 3.6);
  }, [turns]);

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
    <div className="relative flex h-full min-w-0">
      {/* ------------------------------------------------- conversation column */}
      {/* The transcript keeps a hard floor: panels squeeze, the conversation does not. */}
      <div className="relative flex min-w-0 flex-1 shrink-0 basis-[380px] flex-col max-lg:basis-auto">
        {/* thread menu */}
        <div className="pointer-events-none absolute right-2 top-2 z-30">
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
          className="transcript min-h-0 flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-chat px-4 pb-44 pt-10">
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
                  onRegenerate={
                    !streaming && i === turns.length - 1 && !turn.pending ? regenerate : undefined
                  }
                />
              ),
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
          className={`absolute bottom-32 left-1/2 z-30 grid h-9 w-9 -translate-x-1/2 place-items-center rounded-full border border-border bg-surface text-fg-muted shadow-soft transition-all duration-slow ease-expo hover:border-accent-line hover:text-fg ${
            scroller.pinned
              ? "pointer-events-none translate-y-3 scale-90 opacity-0"
              : "translate-y-0 scale-100 opacity-100"
          }`}
        >
          <IcoArrowDown size={16} />
        </button>

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
          models={models}
          model={model}
          setModel={setModel}
          services={services}
          setServices={setServices}
          contextUsed={contextUsed}
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
  register,
}: {
  turn: ChatTurn;
  language: Language;
  streaming: boolean;
  onRegenerate?: () => void;
  onOpenArtifact: (a: Artifact) => void;
  register: (id: string, el: HTMLElement | null) => void;
}) {
  const nothingYet = turn.blocks.length === 0 && !turn.thinking;

  return (
    <div ref={(el) => register(turn.id, el)} data-turn-id={turn.id} className="animate-rise mb-2">
      {turn.thinking && <Reasoning text={turn.thinking} active={turn.pending} language={language} />}

      {/* The block timeline: prose and work interleaved in the order they happened. */}
      {turn.blocks.map((b, i) =>
        isText(b) ? (
          b.text.trim() ? (
            <Markdown
              key={b.id}
              text={b.text}
              streaming={streaming && i === turn.blocks.length - 1}
              onOpenArtifact={onOpenArtifact}
            />
          ) : null
        ) : (
          <StepChip key={b.id} step={b} language={language} onOpenArtifact={onOpenArtifact} />
        ),
      )}

      {/* No prebuilt loader. Just an honest, unbounded presence indicator that
          says "still here" without implying a duration. */}
      {turn.pending && nothingYet && (
        <div className="flex items-center gap-2 py-1">
          <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />
          <span className="h-px w-8 bg-border" />
        </div>
      )}

      {turn.artifacts.length > 0 && (
        <InlineArtifacts artifacts={turn.artifacts} onOpen={onOpenArtifact} language={language} />
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

function InlineArtifacts({
  artifacts,
  onOpen,
  language,
}: {
  artifacts: Artifact[];
  onOpen: (a: Artifact) => void;
  language: Language;
}) {
  return (
    <div className="mt-4">
      <div className="eyebrow mb-1.5">{language === "sw" ? "Matokeo" : "Output"}</div>
      <div className="flex flex-wrap gap-1.5">
        {artifacts.map((a, i) => (
          <button
            key={i}
            onClick={() => onOpen(a)}
            className="group inline-flex max-w-full items-center gap-1.5 border border-border bg-surface px-2.5 py-1.5 text-xs text-fg-muted transition-all duration-fast ease-soft hover:border-accent-line hover:text-fg"
          >
            <span className="truncate">{a.name}</span>
          </button>
        ))}
      </div>
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
