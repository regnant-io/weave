"use client";

import { useEffect, useRef, useState } from "react";
import type { Language } from "@/lib/types";

/**
 * Redirect the model while it is still working.
 *
 * Appears only during a turn, directly above the composer, because that is
 * where the user's hands already are when they realise the answer is going the
 * wrong way. The quick actions cover the three things people actually want to
 * say mid-stream — go deeper, move on, stop guessing and ask me — and the free
 * text field covers everything else.
 *
 * Sending is deliberately not disabled while a redirect is in flight: a user who
 * wants to say two things should be able to, and the server queues them.
 */
export default function SteerBar({
  language,
  note,
  onSteer,
}: {
  language: Language;
  /** Transient feedback from the steering path, or null. */
  note: string | null;
  onSteer: (text: string, kind?: string) => void;
}) {
  const sw = language === "sw";
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const quick: Array<{ label: string; text: string; kind: string }> = sw
    ? [
        { label: "Fupisha", text: "Kuwa mfupi zaidi — nipe jibu moja kwa moja.", kind: "focus" },
        { label: "Ruka hii", text: "Acha unachofanya sasa na uende hatua inayofuata.", kind: "skip" },
        { label: "Niulize", text: "Usikisie — niulize unachohitaji kujua.", kind: "ask" },
      ]
    : [
        { label: "Shorter", text: "Be much shorter — just give me the answer.", kind: "focus" },
        { label: "Skip this", text: "Drop what you are doing and move to the next step.", kind: "skip" },
        { label: "Ask me", text: "Stop guessing — ask me what you need to know.", kind: "ask" },
      ];

  function submit() {
    const value = text.trim();
    if (!value) return;
    onSteer(value, "redirect");
    setText("");
    setOpen(false);
  }

  return (
    <div className="animate-fade border-t border-border bg-surface-2/70 px-3 py-2 backdrop-blur">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="eyebrow flex-shrink-0">{sw ? "Elekeza" : "Steer"}</span>

        {quick.map((q) => (
          <button
            key={q.label}
            onClick={() => onSteer(q.text, q.kind)}
            className="rounded-full border border-border px-2.5 py-1 text-[11.5px] text-fg-muted transition-colors duration-fast hover:border-accent-line hover:text-accent"
          >
            {q.label}
          </button>
        ))}

        {open ? (
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <input
              ref={inputRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
                if (e.key === "Escape") setOpen(false);
              }}
              placeholder={sw ? "Badilisha mwelekeo…" : "Change direction…"}
              className="min-w-0 flex-1 border border-border bg-bg px-2.5 py-1 text-[16px] outline-none focus:border-accent-line sm:text-[12.5px]"
            />
            <button
              onClick={submit}
              disabled={!text.trim()}
              className="rounded-full border border-accent bg-accent px-2.5 py-1 text-[11.5px] text-white disabled:opacity-40"
            >
              {sw ? "Tuma" : "Send"}
            </button>
          </div>
        ) : (
          <button
            onClick={() => setOpen(true)}
            className="rounded-full border border-dashed border-border px-2.5 py-1 text-[11.5px] text-fg-faint transition-colors duration-fast hover:border-accent-line hover:text-accent"
          >
            {sw ? "Andika maelekezo…" : "Type a redirect…"}
          </button>
        )}
      </div>

      {note && <p className="mt-1.5 text-[11.5px] text-fg-muted">{note}</p>}
    </div>
  );
}
