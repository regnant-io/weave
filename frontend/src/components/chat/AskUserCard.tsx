"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Language } from "@/lib/types";
import type { AskUserRequest } from "@/lib/chatTypes";
import { IcoCheck, IcoSparkles } from "@/components/ui/icons";

/**
 * The assistant asking the user a question, mid-turn.
 *
 * The turn is genuinely BLOCKED on this: a worker thread on the server is parked
 * waiting for the POST this component sends. Three consequences shape the UI:
 *
 *   * It must be obvious that something is waiting on you. Hence the accent
 *     border and the "waiting" state, rather than a quiet inline prompt.
 *   * It must always be answerable. Every question accepts free text as well as
 *     the offered options, because the model's options are a guess and the right
 *     answer is sometimes none of them.
 *   * It must not trap the user. "Let me decide" sends an explicit skip so the
 *     model proceeds on its own judgement instead of the turn hanging until the
 *     server-side timeout.
 */
export default function AskUserCard({
  request,
  language,
  onAnswered,
}: {
  request: AskUserRequest;
  language: Language;
  onAnswered: (id: string) => void;
}) {
  const sw = language === "sw";
  const [selections, setSelections] = useState<Record<string, string[]>>({});
  const [custom, setCustom] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const questions = request.questions ?? [];

  const answered = request.answered;

  const complete = useMemo(
    () =>
      questions.every((q) => {
        const picked = selections[q.question]?.length;
        const typed = (custom[q.question] || "").trim().length;
        return Boolean(picked || typed);
      }),
    [questions, selections, custom],
  );

  const toggle = useCallback(
    (question: string, label: string, multi: boolean) => {
      setSelections((prev) => {
        const cur = prev[question] ?? [];
        if (!multi) return { ...prev, [question]: cur[0] === label ? [] : [label] };
        return {
          ...prev,
          [question]: cur.includes(label) ? cur.filter((l) => l !== label) : [...cur, label],
        };
      });
    },
    [],
  );

  async function submit(skip = false) {
    if (sending) return;
    setSending(true);
    setError(null);

    const answers: Record<string, string> = {};
    if (!skip) {
      for (const q of questions) {
        const picked = selections[q.question] ?? [];
        const typed = (custom[q.question] || "").trim();
        // A typed answer is appended rather than replacing the picks: "option B,
        // but only for 2019" is a real and common shape of answer.
        const parts = [...picked, ...(typed ? [typed] : [])];
        if (parts.length) answers[q.question] = parts.join(", ");
      }
    }

    try {
      const res = await fetch(`/api/interactions/${encodeURIComponent(request.id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          answers,
          notes: skip
            ? "The user asked you to decide. State the assumption you made."
            : notes.trim(),
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      onAnswered(request.id);
    } catch {
      setError(
        sw
          ? "Imeshindwa kutuma jibu. Huenda swali limepitwa na wakati."
          : "Could not send your answer — the question may have expired.",
      );
      setSending(false);
    }
  }

  // Escape is a natural "you decide" — but only while the question is live.
  useEffect(() => {
    if (answered) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void submit(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answered]);

  if (answered) {
    return (
      <div className="animate-rise my-3 flex items-start gap-2 border-l-2 border-ok pl-3 text-[13px] text-fg-muted">
        <IcoCheck size={13} className="mt-[3px] flex-shrink-0 text-ok" />
        <span>{sw ? "Umejibu — kazi inaendelea." : "Answered — continuing."}</span>
      </div>
    );
  }

  return (
    <div className="animate-rise my-4 overflow-hidden rounded-sm border border-accent-line bg-surface">
      <div className="flex items-center gap-2 border-b border-border bg-accent-soft px-3 py-2">
        <IcoSparkles size={13} className="flex-shrink-0 text-accent" />
        <span className="eyebrow text-accent">
          {sw ? "Swali kwako" : "A question for you"}
        </span>
        <span className="ml-auto flex items-center gap-1.5 text-[11px] text-fg-faint">
          <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />
          {sw ? "inasubiri" : "waiting"}
        </span>
      </div>

      <div className="space-y-4 px-3 py-3">
        {questions.map((q) => {
          const picked = selections[q.question] ?? [];
          return (
            <div key={q.question}>
              {q.header && <div className="eyebrow mb-1">{q.header}</div>}
              <p className="mb-2 font-read text-[15px] leading-snug text-fg">{q.question}</p>

              {q.options.length > 0 && (
                <div className="mb-2 grid gap-1.5">
                  {q.options.map((o) => {
                    const on = picked.includes(o.label);
                    return (
                      <button
                        key={o.label}
                        type="button"
                        onClick={() => toggle(q.question, o.label, Boolean(q.multi_select))}
                        aria-pressed={on}
                        className={`flex w-full items-start gap-2.5 rounded-sm border px-2.5 py-2 text-left transition-all duration-fast ease-soft ${
                          on
                            ? "border-accent bg-accent-soft"
                            : "border-border hover:border-border-mid hover:bg-surface-hover"
                        }`}
                      >
                        <span
                          className={`mt-[3px] grid h-3.5 w-3.5 flex-shrink-0 place-items-center border ${
                            q.multi_select ? "rounded-sm" : "rounded-full"
                          } ${on ? "border-accent bg-accent" : "border-border-mid"}`}
                        >
                          {on && <IcoCheck size={9} className="text-accent-fg" strokeWidth={3} />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13.5px] leading-snug text-fg">
                            {o.label}
                          </span>
                          {o.description && (
                            <span className="mt-0.5 block text-[12px] leading-snug text-fg-muted">
                              {o.description}
                            </span>
                          )}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              <input
                value={custom[q.question] ?? ""}
                onChange={(e) => setCustom((p) => ({ ...p, [q.question]: e.target.value }))}
                placeholder={
                  q.options.length
                    ? sw
                      ? "Au andika jibu lako…"
                      : "Or type your own answer…"
                    : sw
                      ? "Jibu lako…"
                      : "Your answer…"
                }
                /* 16px so iOS does not zoom the page on focus. */
                className="w-full rounded-sm border border-border bg-bg px-2.5 py-1.5 text-[16px] outline-none transition-colors duration-fast focus:border-accent-line sm:text-[13.5px]"
              />
            </div>
          );
        })}

        {questions.length > 1 && (
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={sw ? "Maelezo ya ziada (hiari)" : "Anything else to add (optional)"}
            className="w-full rounded-sm border border-border bg-bg px-2.5 py-1.5 text-[16px] outline-none transition-colors duration-fast focus:border-accent-line sm:text-[13.5px]"
          />
        )}

        {error && <p className="text-[12px] text-danger">{error}</p>}

        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <button
            type="button"
            onClick={() => void submit(false)}
            disabled={!complete || sending}
            className="rounded-full bg-accent px-4 py-1.5 text-[13px] font-medium text-accent-fg transition-opacity duration-fast hover:opacity-90 disabled:opacity-35"
          >
            {sending ? (sw ? "Inatuma…" : "Sending…") : sw ? "Tuma jibu" : "Send answer"}
          </button>
          <button
            type="button"
            onClick={() => void submit(true)}
            disabled={sending}
            className="rounded-full border border-border px-3 py-1.5 text-[13px] text-fg-muted transition-colors duration-fast hover:border-border-mid hover:text-fg disabled:opacity-50"
          >
            {sw ? "Amua wewe" : "You decide"}
          </button>
        </div>
      </div>
    </div>
  );
}
