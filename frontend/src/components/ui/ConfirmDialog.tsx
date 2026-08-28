"use client";

import { useEffect, useRef, useState } from "react";
import type { Language } from "@/lib/types";
import { IcoWarn } from "@/components/ui/icons";

/**
 * Confirmation before something irreversible.
 *
 * Deliberately not a `window.confirm`: that cannot say what will be destroyed,
 * cannot be styled, and on iOS is dismissed by an accidental tap outside. The
 * cost of an unwanted delete here is a user's entire research project, so:
 *
 *   * the body states exactly what is lost, in the user's language;
 *   * Cancel is focused on open, so a reflexive Enter is safe;
 *   * `requirePhrase` forces the truly catastrophic action (delete EVERY
 *     project) to be typed out — a button alone is too easy to hit twice.
 */
export default function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel,
  language,
  tone = "danger",
  requirePhrase,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  language: Language;
  tone?: "danger" | "accent";
  /** When set, the user must type this exactly before confirming. */
  requirePhrase?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const sw = language === "sw";
  const [typed, setTyped] = useState("");
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      setTyped("");
      return;
    }
    // Focus Cancel, not Confirm: a keyboard user who hits Enter out of habit
    // must not destroy anything.
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onCancel]);

  if (!open) return null;

  const ready = !requirePhrase || typed.trim() === requirePhrase;
  const confirmClass =
    tone === "danger"
      ? "bg-danger text-white hover:opacity-90"
      : "bg-accent text-accent-fg hover:opacity-90";

  return (
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center bg-black/45 p-3 sm:items-center"
      onClick={onCancel}
      role="presentation"
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(e) => e.stopPropagation()}
        className="animate-rise w-full max-w-md overflow-hidden rounded-lg border border-border bg-surface shadow-lg"
        style={{ marginBottom: "var(--safe-bottom)" }}
      >
        <div className="flex items-start gap-3 px-4 pb-3 pt-4">
          <span
            className={`mt-0.5 grid h-8 w-8 flex-shrink-0 place-items-center rounded-full ${
              tone === "danger" ? "bg-danger-soft text-danger" : "bg-accent-soft text-accent"
            }`}
          >
            <IcoWarn size={16} />
          </span>
          <div className="min-w-0">
            <h2 id="confirm-title" className="text-[15px] font-semibold">
              {title}
            </h2>
            <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">{body}</p>
          </div>
        </div>

        {requirePhrase && (
          <div className="px-4 pb-1">
            <label className="block text-[12px] text-fg-muted">
              {sw ? "Andika" : "Type"}{" "}
              <span className="font-mono text-fg">{requirePhrase}</span>{" "}
              {sw ? "kuthibitisha" : "to confirm"}
            </label>
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
              className="mt-1 w-full rounded-sm border border-border bg-bg px-2.5 py-1.5 font-mono text-[16px] outline-none transition-colors duration-fast focus:border-danger sm:text-[13px]"
            />
          </div>
        )}

        <div className="flex justify-end gap-2 px-4 pb-4 pt-3">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="rounded-full border border-border px-4 py-1.5 text-[13px] text-fg-muted transition-colors duration-fast hover:border-border-mid hover:text-fg"
          >
            {cancelLabel ?? (sw ? "Ghairi" : "Cancel")}
          </button>
          <button
            onClick={onConfirm}
            disabled={!ready}
            className={`rounded-full px-4 py-1.5 text-[13px] font-medium transition-opacity duration-fast disabled:opacity-35 ${confirmClass}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
