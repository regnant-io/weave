"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Dataset, Effort, Language } from "@/lib/types";
import type { ServiceId, ServicePrefs } from "@/lib/services";
import { formatTokens, type ModelInfo } from "@/lib/models";
import { t } from "@/lib/i18n";
import {
  IcoArrowUp,
  IcoChart,
  IcoChevronDown,
  IcoDataset,
  IcoGlobe,
  IcoSparkles,
  IcoStop,
  IcoTelescope,
  IcoTerminal,
} from "@/components/ui/icons";

export type { ModelInfo };

const EFFORTS: { id: Effort; label: string; hint: [string, string] }[] = [
  { id: "spool", label: "Spool", hint: ["haraka", "quick"] },
  { id: "weave", label: "Weave", hint: ["sawia", "balanced"] },
  { id: "tapestry", label: "Tapestry", hint: ["kina", "deep"] },
];

const SERVICES: { id: ServiceId; icon: any; label: [string, string]; hint: [string, string] }[] = [
  {
    id: "web_search",
    icon: IcoGlobe,
    label: ["Mtandao", "Web"],
    hint: ["Tafuta mtandaoni kila wakati", "Search the web on every turn"],
  },
  {
    id: "deep_research",
    icon: IcoTelescope,
    label: ["Utafiti", "Deep research"],
    hint: ["Soma vyanzo kwa kina", "Iteratively read sources in depth"],
  },
  {
    id: "analysis",
    icon: IcoTerminal,
    label: ["Uchambuzi", "Analysis"],
    hint: ["Endesha Python kwenye data", "Run Python against your data"],
  },
  {
    id: "visuals",
    icon: IcoChart,
    label: ["Taswira", "Visuals"],
    hint: ["Chati, michoro, uigaji, 3D", "Charts, diagrams, simulations, 3D"],
  },
];

/* ------------------------------------------------------------- popover base */

/**
 * Composer popover.
 *
 * The menu is rendered into a PORTAL with fixed positioning rather than
 * absolutely inside the trigger. It has to be: the control rail is
 * `overflow-x-auto` so it can scroll on narrow screens, and once one overflow
 * axis is non-visible CSS computes the other to `auto` too — which means the
 * rail clips its descendants vertically. An `absolute bottom-full` menu sits
 * above the rail's top edge, i.e. squarely inside the clipped region, so it
 * simply disappeared. No z-index can fix clipping.
 *
 * Portalling to <body> also sidesteps the stacking context created by the
 * composer's own `z-20` wrapper, so the menu can never end up behind the
 * artifact panel.
 */
function Popover({
  label,
  icon,
  children,
  width = 224,
  active,
}: {
  label: React.ReactNode;
  icon?: React.ReactNode;
  children: (close: () => void) => React.ReactNode;
  /** Menu width in px (fixed positioning means no Tailwind width class). */
  width?: number;
  active?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [pos, setPos] = useState({ left: 0, bottom: 0, width });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => setMounted(true), []);

  const place = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const w = Math.min(width, window.innerWidth - 16);
    // Prefer left-aligned with the trigger, but never overflow the viewport.
    const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
    setPos({ left, bottom: Math.max(8, window.innerHeight - r.top + 8), width: w });
  }, [width]);

  // Position before paint so the menu never flashes at the wrong coordinates.
  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    const onPointer = (e: PointerEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      close();
    };
    // A fixed menu does not travel with a scrolling ancestor, so following the
    // trigger is the wrong behaviour — dismiss instead.
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onPointer, true);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onPointer, true);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", close, true);
    };
  }, [open, place]);

  return (
    <>
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={id}
        aria-haspopup="menu"
        className={`flex max-w-[11rem] flex-shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-all duration-fast ease-soft ${
          active
            ? "border-accent-line bg-accent-soft text-fg"
            : "border-border bg-surface text-fg-muted hover:border-border-mid hover:text-fg"
        }`}
      >
        {icon}
        <span className="truncate">{label}</span>
        <IcoChevronDown size={12} className="chev flex-shrink-0 opacity-60" data-open={open} />
      </button>

      {mounted &&
        open &&
        createPortal(
          <div
            id={id}
            ref={menuRef}
            role="menu"
            style={{ left: pos.left, bottom: pos.bottom, width: pos.width }}
            className="animate-rise fixed z-[70] max-h-[min(60vh,26rem)] overflow-auto border border-border bg-surface shadow-lg"
          >
            {children(() => setOpen(false))}
          </div>,
          document.body,
        )}
    </>
  );
}

/* ------------------------------------------------------------ context meter */

/**
 * Live context usage for the selected model.
 *
 * Token counts are estimated (chars/3.6 across mixed English+Kiswahili prose,
 * which runs slightly denser than the usual chars/4 rule of thumb). It is a
 * gauge, not an accounting record — its job is to warn before a long session
 * silently starts dropping the earliest turns out of the window.
 */
function ContextMeter({
  used,
  limit,
  language,
}: {
  used: number;
  limit: number;
  language: Language;
}) {
  if (!limit) return null;
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const tone = pct >= 90 ? "bg-danger" : pct >= 70 ? "bg-warn" : "bg-accent";
  return (
    <div
      className="flex items-center gap-1.5"
      title={
        language === "sw"
          ? `Muktadha: takribani tokeni ${used} kati ya ${limit}. Ukifika kikomo, mazungumzo hufupishwa na kuendelea kwenye gumzo jipya.`
          : `Context: ~${used} of ${limit} tokens. At the limit this chat is summarised and continued in a new one.`
      }
    >
      <div className="h-1 w-12 overflow-hidden rounded-full bg-surface-3">
        <div
          className={`h-full ${tone} transition-[width] duration-slow ease-expo`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[10px] tabular-nums text-fg-faint">
        {formatTokens(used)}/{formatTokens(limit)}
      </span>
    </div>
  );
}

/* -------------------------------------------------------------------- main */

export default function Composer({
  input,
  setInput,
  onSend,
  onStop,
  streaming,
  language,
  datasets,
  datasetId,
  setDatasetId,
  effort,
  setEffort,
  models,
  model,
  setModel,
  services,
  setServices,
  contextUsed,
  contextLimit,
  above,
}: {
  input: string;
  setInput: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  language: Language;
  datasets: Dataset[];
  datasetId: string;
  setDatasetId: (v: string) => void;
  effort: Effort;
  setEffort: (e: Effort) => void;
  models: ModelInfo[];
  model: string;
  setModel: (m: string) => void;
  services: ServicePrefs;
  setServices: (s: ServicePrefs) => void;
  contextUsed: number;
  /** The selected model's REAL window, resolved server-side. 0 hides the meter. */
  contextLimit: number;
  /**
   * Rendered directly above the control rail, INSIDE the composer's own
   * overlay: the steering bar while a turn is running, the live-voice bar when
   * one is not. See the comment at the render site for why they cannot be
   * siblings.
   */
  above?: React.ReactNode;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const sw = language === "sw";
  const label = (p: [string, string]) => (sw ? p[0] : p[1]);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  }, [input]);

  /*
    Publish the composer's real height as `--composer-h`.

    The transcript is a scroller with the composer floating over its bottom
    edge, so it has to pad itself by however much the composer covers. That was
    a hard-coded 11rem, which is right for a one-line input and wrong the moment
    the composer grows — a multi-line draft (the textarea expands to 200px), the
    steering bar appearing mid-turn, the control rail wrapping on a narrow
    phone. In every one of those cases the last line of the answer disappeared
    underneath the input.

    Measuring is the only thing that stays correct, and a ResizeObserver on the
    overlay catches all three causes without any of them knowing about each
    other. The variable goes on the document element so the scroll-to-bottom
    button can ride on the same number.
  */
  useEffect(() => {
    const el = shellRef.current;
    if (!el) return;
    const publish = () =>
      document.documentElement.style.setProperty(
        "--composer-h",
        `${Math.round(el.getBoundingClientRect().height)}px`,
      );
    publish();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(publish);
    ro.observe(el);
    return () => {
      ro.disconnect();
      document.documentElement.style.removeProperty("--composer-h");
    };
  }, []);

  const activeServices = SERVICES.filter((s) => services[s.id]);
  const inputTokens = Math.ceil(input.length / 3.6);

  function toggle(id: ServiceId) {
    const next = { ...services, [id]: !services[id] };
    setServices(next);
    fetch("/api/prefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ services: next }),
    }).catch(() => {});
  }

  return (
    <div
      ref={shellRef}
      className="pointer-events-none absolute inset-x-0 bottom-0 z-20"
      /*
        --kb-inset lifts the composer clear of the iOS on-screen keyboard. iOS
        shrinks only the VISUAL viewport, so `bottom: 0` is still the bottom of
        the (unchanged) layout viewport — i.e. underneath the keyboard. That is
        the "input hides below the screen" bug; there is no CSS-only fix.
      */
      style={{
        transform: "translateY(calc(-1 * var(--kb-inset)))",
        transition: "transform 180ms var(--ease-out-soft)",
      }}
    >
      {/* Fade so text dissolves under the composer instead of being clipped. */}
      <div className="pointer-events-none h-14 bg-gradient-to-t from-bg via-bg/90 to-transparent" />
      <div
        className="bg-bg px-2 sm:px-3"
        style={{ paddingBottom: "calc(0.75rem + var(--safe-bottom))" }}
      >
        <div className="pointer-events-auto mx-auto w-full min-w-0 max-w-chat">
          {/*
            ANYTHING ANCHORED ABOVE THE INPUT BELONGS INSIDE THIS OVERLAY.

            The steering bar and the live-voice bar used to be rendered as
            siblings of the composer, in normal flow at the bottom of the chat
            column. The composer is `absolute; bottom: 0; z-20`, so it was
            painted directly on top of both of them: the bar that lets you
            redirect a running turn, and the entry point to voice and screen
            sharing, were laid out at exactly the coordinates the composer
            covers and were therefore invisible and unclickable. Nothing errored
            and the DOM looked right, which is why it survived.

            Putting them in here also means `--composer-h` below measures the
            real occupied height including them, so the transcript's bottom
            padding is correct whether or not a bar is showing.
          */}
          {above}
          {/* control rail */}
          <div className="hide-scrollbar mb-1.5 flex items-center gap-1.5 overflow-x-auto px-0.5 pb-0.5">
            <Popover
              label={EFFORTS.find((e) => e.id === effort)!.label}
              icon={<IcoSparkles size={12} className="text-accent" />}
            >
              {(close) => (
                <div>
                  {EFFORTS.map((e) => (
                    <button
                      key={e.id}
                      onClick={() => {
                        setEffort(e.id);
                        fetch("/api/prefs", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ effort: e.id }),
                        }).catch(() => {});
                        close();
                      }}
                      className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors duration-fast hover:bg-surface-hover ${
                        effort === e.id ? "text-accent" : "text-fg"
                      }`}
                    >
                      <span>{e.label}</span>
                      <span className="eyebrow">{label(e.hint)}</span>
                    </button>
                  ))}
                </div>
              )}
            </Popover>

            {models.length > 0 && (
              <Popover label={model || "model"} width={288}>
                {(close) => (
                  <div>
                    {models.map((m) => (
                      <button
                        key={m.name}
                        onClick={() => {
                          setModel(m.name);
                          close();
                        }}
                        className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors duration-fast hover:bg-surface-hover ${
                          model === m.name ? "text-accent" : "text-fg"
                        }`}
                      >
                        <span className="min-w-0 flex-1 truncate">{m.name}</span>
                        {m.context ? (
                          <span className="eyebrow flex-shrink-0">{formatTokens(m.context)}</span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                )}
              </Popover>
            )}

            <Popover
              label={
                activeServices.length
                  ? activeServices.map((s) => label(s.label)).join(" · ")
                  : sw
                    ? "Huduma"
                    : "Services"
              }
              width={288}
              active={activeServices.length > 0}
            >
              {() => (
                <div className="py-1">
                  <div className="eyebrow px-3 pb-1.5 pt-1">
                    {sw ? "Tumia kila wakati" : "Always use"}
                  </div>
                  {SERVICES.map((s) => {
                    const Icon = s.icon;
                    const on = services[s.id];
                    return (
                      <button
                        key={s.id}
                        onClick={() => toggle(s.id)}
                        className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors duration-fast hover:bg-surface-hover"
                      >
                        <Icon size={15} className={`mt-0.5 ${on ? "text-accent" : "text-fg-faint"}`} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm text-fg">{label(s.label)}</span>
                          <span className="block text-[11px] leading-snug text-fg-faint">
                            {label(s.hint)}
                          </span>
                        </span>
                        <span
                          className={`mt-1 h-3.5 w-6 flex-shrink-0 rounded-full transition-colors duration-fast ${
                            on ? "bg-accent" : "bg-surface-3"
                          }`}
                        >
                          <span
                            className={`block h-3.5 w-3.5 rounded-full bg-bg shadow-sm transition-transform duration-fast ease-soft ${
                              on ? "translate-x-2.5" : "translate-x-0"
                            }`}
                          />
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </Popover>

            {datasets.length > 0 && (
              <Popover
                label={
                  datasets.find((d) => d.id === datasetId)?.original_filename ??
                  (sw ? "Hakuna data" : "No dataset")
                }
                icon={<IcoDataset size={12} />}
                width={256}
                active={Boolean(datasetId)}
              >
                {(close) => (
                  <div>
                    <button
                      onClick={() => {
                        setDatasetId("");
                        close();
                      }}
                      className="block w-full px-3 py-2 text-left text-sm text-fg-muted transition-colors duration-fast hover:bg-surface-hover"
                    >
                      {sw ? "Hakuna data" : "No dataset"}
                    </button>
                    {datasets.map((d) => (
                      <button
                        key={d.id}
                        onClick={() => {
                          setDatasetId(d.id);
                          close();
                        }}
                        className={`block w-full truncate px-3 py-2 text-left text-sm transition-colors duration-fast hover:bg-surface-hover ${
                          datasetId === d.id ? "text-accent" : "text-fg"
                        }`}
                      >
                        {d.original_filename}
                      </button>
                    ))}
                  </div>
                )}
              </Popover>
            )}

            <div className="ml-auto flex-shrink-0 pl-2">
              <ContextMeter
                used={contextUsed + inputTokens}
                limit={contextLimit}
                language={language}
              />
            </div>
          </div>

          {/* input */}
          {/*
            Focus is expressed as a ring the whole field participates in, rather
            than a single border colour change: at 1px the old treatment was
            nearly invisible against --border on a bright phone screen. The
            outline is suppressed because the ring IS the focus indicator.
          */}
          <div className="composer-field flex items-end gap-2 rounded-lg border border-border bg-surface px-2 py-1.5 shadow-soft">
            <textarea
              ref={taRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSend();
                }
              }}
              placeholder={t("askPlaceholder", language)}
              /* enterKeyHint labels the iOS return key; autoCapitalize keeps a
                 Kiswahili sentence from being auto-capitalised mid-thought. */
              enterKeyHint="send"
              autoCapitalize="sentences"
              autoCorrect="on"
              /* 16px minimum: below that, iOS Safari ZOOMS the whole page on
                 focus and the layout never fully recovers. */
              className="max-h-[200px] min-w-0 flex-1 resize-none bg-transparent px-2 py-1.5 font-read text-[16px] leading-relaxed outline-none placeholder:italic placeholder:text-fg-faint sm:text-[15.5px]"
            />
            {streaming ? (
              <button
                onClick={onStop}
                aria-label={sw ? "Simamisha" : "Stop"}
                className="mb-0.5 grid h-8 w-8 flex-shrink-0 place-items-center rounded-full bg-fg text-bg transition-all duration-fast ease-soft hover:opacity-90 active:scale-95"
              >
                <IcoStop size={12} className="fill-current" />
              </button>
            ) : (
              <button
                onClick={onSend}
                disabled={!input.trim()}
                aria-label={t("send", language)}
                className="mb-0.5 grid h-8 w-8 flex-shrink-0 place-items-center rounded-full bg-accent text-accent-fg transition-all duration-fast ease-soft hover:bg-accent-strong active:scale-95 disabled:opacity-25"
              >
                <IcoArrowUp size={15} strokeWidth={2} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
