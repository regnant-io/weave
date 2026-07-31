"use client";

import { useEffect, useRef } from "react";
import type { Language } from "@/lib/types";
import { useLiveSession } from "./useLiveSession";

/**
 * The live session surface: talk, be listened to, share a screen.
 *
 * Collapsed to a single button until it is started, because a chat window that
 * permanently shows microphone controls implies the microphone is doing
 * something. It is not, until you press it.
 *
 * Once live, the bar shows exactly three things — what it heard, what it is
 * doing, and how to stop it. Everything else is noise in a mode where the user
 * is looking at their screen rather than at this panel.
 */
export default function LiveBar({
  projectId,
  language,
}: {
  projectId: string;
  language: Language;
}) {
  const sw = language === "sw";
  const live = useLiveSession(projectId, language === "sw" ? "sw" : "en");
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [live.transcript, live.interim]);

  if (!live.supported) {
    return (
      <p className="px-3 py-2 text-[11.5px] leading-relaxed text-fg-faint">
        {sw
          ? "Kivinjari hiki hakiwezi kutumia sauti moja kwa moja. Jaribu Chrome kwenye Android au kompyuta."
          : "This browser cannot do live voice. Chrome on Android or a desktop will work."}
      </p>
    );
  }

  if (live.state === "off") {
    return (
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button
          onClick={() => void live.start({ ambient: false })}
          className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-[12.5px] text-fg-muted transition-colors duration-fast hover:border-accent-line hover:text-accent"
        >
          <Dot className="bg-fg-faint" />
          {sw ? "Ongea na Weave" : "Talk to Weave"}
        </button>
        <button
          onClick={() => void live.start({ ambient: true })}
          title={
            sw
              ? "Weave husikiliza lakini hujibu tu ukimwita au ukiuliza swali"
              : "Weave listens but only answers when you name it or ask a question"
          }
          className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border px-3 py-1.5 text-[12.5px] text-fg-faint transition-colors duration-fast hover:border-accent-line hover:text-accent"
        >
          {sw ? "Hali ya usikilizaji" : "Ambient mode"}
        </button>
        {live.error && <span className="text-[11.5px] text-danger">{live.error}</span>}
      </div>
    );
  }

  const stateLabel =
    live.state === "connecting"
      ? sw ? "Inaunganisha…" : "Connecting…"
      : live.state === "listening"
        ? sw ? "Inasikiliza" : "Listening"
        : live.state === "thinking"
          ? sw ? "Inafikiri…" : "Thinking…"
          : live.state === "speaking"
            ? sw ? "Inaongea" : "Speaking"
            : sw ? "Hitilafu" : "Error";

  return (
    <div className="border-t border-border bg-surface-2/70 backdrop-blur">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <Dot
          className={
            live.state === "listening"
              ? "animate-pulse bg-accent"
              : live.state === "speaking"
                ? "bg-accent"
                : live.state === "error"
                  ? "bg-danger"
                  : "bg-fg-faint"
          }
        />
        <span className="text-[12.5px] text-fg">{stateLabel}</span>

        {live.cue && (
          <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] text-accent">
            {live.cue}
          </span>
        )}

        <label className="ml-auto flex items-center gap-1.5 text-[11.5px] text-fg-muted">
          <input
            type="checkbox"
            checked={live.ambient}
            onChange={(e) => live.setAmbientMode(e.target.checked)}
          />
          {sw ? "Usikilizaji" : "Ambient"}
        </label>

        <button
          onClick={() => (live.sharing ? live.stopScreen() : void live.startScreen())}
          className={`rounded-full border px-2.5 py-1 text-[11.5px] transition-colors duration-fast ${
            live.sharing
              ? "border-accent text-accent"
              : "border-border text-fg-muted hover:border-accent-line hover:text-accent"
          }`}
        >
          {live.sharing
            ? sw ? "Acha kushiriki skrini" : "Stop sharing"
            : sw ? "Shiriki skrini" : "Share screen"}
        </button>

        <button
          onClick={live.stop}
          className="rounded-full border border-border px-2.5 py-1 text-[11.5px] text-fg-faint hover:border-danger hover:text-danger"
        >
          {sw ? "Simamisha" : "End"}
        </button>
      </div>

      {live.ambient && (
        <p className="px-3 pb-1.5 text-[10.5px] leading-relaxed text-fg-faint">
          {sw
            ? "Weave anasikiliza lakini atajibu tu ukisema jina lake, ukiuliza swali, au mara baada ya kuongea nawe."
            : "Weave is listening but will only answer when you say its name, ask a question, or follow up just after it spoke."}
        </p>
      )}

      <div ref={logRef} className="max-h-40 overflow-y-auto px-3 pb-2">
        {live.transcript.map((entry) => (
          <p
            key={entry.id}
            className={`text-[12px] leading-relaxed ${
              entry.who === "assistant" ? "text-fg" : "text-fg-muted"
            }`}
          >
            <span className="eyebrow mr-1.5">
              {entry.who === "assistant" ? "weave" : sw ? "wewe" : "you"}
            </span>
            {entry.text}
            {entry.who === "user" && entry.responding === false && (
              <span className="ml-1.5 text-[10.5px] text-fg-faint">
                ({sw ? "haikujibiwa" : "not addressed"})
              </span>
            )}
          </p>
        ))}
        {live.interim && (
          <p className="text-[12px] italic leading-relaxed text-fg-faint">{live.interim}</p>
        )}
      </div>

      {live.error && (
        <p className="px-3 pb-2 text-[11.5px] text-danger">{live.error}</p>
      )}
    </div>
  );
}

function Dot({ className }: { className: string }) {
  return <span className={`h-2 w-2 flex-shrink-0 rounded-full ${className}`} />;
}
