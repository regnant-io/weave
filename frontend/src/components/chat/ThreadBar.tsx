"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Language, Thread } from "@/lib/types";
import {
  IcoCheck,
  IcoChevronDown,
  IcoClose,
  IcoEdit,
  IcoNewChat,
  IcoTrash,
} from "@/components/ui/icons";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

/**
 * Chats within one project.
 *
 * A project is a research workspace that can run for weeks; forcing all of it
 * into one message list makes it unreadable and eventually unusable, because
 * the earliest turns fall out of the model's window with no signal. Splitting
 * it into named chats fixes the readability problem, and project memory (a
 * summary plus addressable facts, read into every chat's system prompt) is what
 * keeps a NEW chat from starting amnesiac.
 *
 * The bar shows the current chat and, when the server has summarised one into a
 * successor, says so — a chat that silently continued somewhere else would be
 * the most confusing possible outcome.
 */
export default function ThreadBar({
  projectId,
  threads,
  activeId,
  language,
  onSelect,
  onChanged,
}: {
  projectId: string;
  threads: Thread[];
  activeId: string;
  language: Language;
  onSelect: (id: string) => void;
  onChanged: () => void;
}) {
  const sw = language === "sw";
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<Thread | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const active = threads.find((t) => t.id === activeId) ?? threads[0];

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onPointer, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointer, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const newChat = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/threads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "" }),
      });
      if (res.ok) {
        const t = await res.json();
        onChanged();
        if (t?.id) onSelect(t.id);
      }
    } finally {
      setBusy(false);
      setOpen(false);
    }
  }, [busy, projectId, onChanged, onSelect]);

  async function rename(id: string) {
    const title = draft.trim();
    setRenaming(null);
    if (!title) return;
    await fetch(`/api/projects/${projectId}/threads/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).catch(() => {});
    onChanged();
  }

  async function remove(t: Thread) {
    setConfirmDelete(null);
    await fetch(`/api/projects/${projectId}/threads/${t.id}`, { method: "DELETE" }).catch(
      () => {},
    );
    // Land somewhere real: the next chat in the list, or whatever the server
    // auto-created if this was the last one.
    const rest = threads.filter((x) => x.id !== t.id);
    onChanged();
    if (t.id === activeId && rest[0]) onSelect(rest[0].id);
    else if (t.id === activeId) onSelect("");
  }

  if (!threads.length) return null;

  return (
    <>
      <div
        ref={wrapRef}
        /* Sits between the fixed menu button (left) and the thread-options
           button (right); the max-width reserves room for both so nothing
           overlaps at 360px. */
        className="pointer-events-none absolute left-1/2 z-30 flex w-full max-w-[min(24rem,calc(100%-8rem))] -translate-x-1/2 justify-center"
        style={{ top: "calc(0.5rem + var(--safe-top))" }}
      >
        <div className="pointer-events-auto relative flex max-w-full items-center gap-1">
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-haspopup="menu"
            className="flex min-w-0 items-center gap-1.5 rounded-full border border-border bg-surface/90 px-3 py-1 text-[12.5px] text-fg-muted shadow-sm backdrop-blur transition-colors duration-fast hover:border-border-mid hover:text-fg"
          >
            <span className="min-w-0 truncate">{active?.title || (sw ? "Gumzo" : "Chat")}</span>
            {threads.length > 1 && (
              <span className="flex-shrink-0 font-mono text-[10px] text-fg-faint">
                {threads.length}
              </span>
            )}
            <IcoChevronDown size={12} className="chev flex-shrink-0 opacity-60" data-open={open} />
          </button>

          <button
            onClick={newChat}
            disabled={busy}
            aria-label={sw ? "Gumzo jipya" : "New chat"}
            title={sw ? "Gumzo jipya katika mradi huu" : "New chat in this project"}
            className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-full border border-border bg-surface/90 text-fg-faint shadow-sm backdrop-blur transition-colors duration-fast hover:border-accent-line hover:text-accent disabled:opacity-50"
          >
            <IcoNewChat size={14} />
          </button>

          {open && (
            <div
              role="menu"
              className="animate-rise absolute left-0 top-full z-50 mt-1.5 max-h-[60vh] w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-sm border border-border bg-surface shadow-lg"
            >
              <div className="eyebrow border-b border-border px-3 py-2">
                {sw ? "Gumzo katika mradi huu" : "Chats in this project"}
              </div>

              {threads.map((t) => {
                const isActive = t.id === activeId;
                return (
                  <div
                    key={t.id}
                    className={`group flex items-center gap-1 border-b border-border/60 px-2 py-1.5 last:border-b-0 ${
                      isActive ? "bg-accent-soft" : "hover:bg-surface-hover"
                    }`}
                  >
                    {renaming === t.id ? (
                      <>
                        <input
                          autoFocus
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void rename(t.id);
                            if (e.key === "Escape") setRenaming(null);
                          }}
                          className="min-w-0 flex-1 rounded-sm border border-accent-line bg-bg px-2 py-1 text-[16px] outline-none sm:text-[13px]"
                        />
                        <button
                          onClick={() => void rename(t.id)}
                          aria-label={sw ? "Hifadhi" : "Save"}
                          className="grid h-6 w-6 place-items-center text-accent"
                        >
                          <IcoCheck size={13} />
                        </button>
                        <button
                          onClick={() => setRenaming(null)}
                          aria-label={sw ? "Ghairi" : "Cancel"}
                          className="grid h-6 w-6 place-items-center text-fg-faint"
                        >
                          <IcoClose size={13} />
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => {
                            onSelect(t.id);
                            setOpen(false);
                          }}
                          className="min-w-0 flex-1 px-1 py-0.5 text-left"
                        >
                          <span
                            className={`block truncate text-[13px] ${
                              isActive ? "text-accent" : "text-fg"
                            }`}
                          >
                            {t.title || (sw ? "Bila jina" : "Untitled")}
                          </span>
                          <span className="eyebrow mt-0.5 block">
                            {t.message_count} {sw ? "ujumbe" : "messages"}
                            {t.status === "rolled" &&
                              ` · ${sw ? "imefupishwa" : "summarised"}`}
                            {t.parent_thread_id && ` · ${sw ? "mwendelezo" : "continued"}`}
                          </span>
                        </button>
                        <button
                          onClick={() => {
                            setRenaming(t.id);
                            setDraft(t.title);
                          }}
                          aria-label={sw ? "Badilisha jina" : "Rename"}
                          className="grid h-6 w-6 flex-shrink-0 place-items-center text-fg-faint opacity-0 transition-opacity duration-fast hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"
                        >
                          <IcoEdit size={12} />
                        </button>
                        <button
                          onClick={() => setConfirmDelete(t)}
                          aria-label={sw ? "Futa" : "Delete"}
                          className="grid h-6 w-6 flex-shrink-0 place-items-center text-fg-faint opacity-0 transition-opacity duration-fast hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
                        >
                          <IcoTrash size={12} />
                        </button>
                      </>
                    )}
                  </div>
                );
              })}

              <button
                onClick={newChat}
                disabled={busy}
                className="flex w-full items-center gap-2 border-t border-border px-3 py-2 text-left text-[13px] text-fg-muted transition-colors duration-fast hover:bg-surface-hover hover:text-fg disabled:opacity-50"
              >
                <IcoNewChat size={14} className="text-accent" />
                {sw ? "Gumzo jipya" : "New chat"}
              </button>
              <p className="border-t border-border px-3 py-2 text-[11.5px] leading-relaxed text-fg-faint">
                {sw
                  ? "Gumzo jipya bado linakumbuka kazi ya gumzo mengine ya mradi huu."
                  : "A new chat still remembers what the other chats in this project established."}
              </p>
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmDelete !== null}
        language={language}
        title={sw ? "Futa gumzo hili?" : "Delete this chat?"}
        body={
          sw
            ? `"${confirmDelete?.title || "Bila jina"}" na ujumbe wake wote utafutwa. Kumbukumbu ya mradi itabaki. Kitendo hiki hakiwezi kutenduliwa.`
            : `"${confirmDelete?.title || "Untitled"}" and all its messages will be deleted. Project memory is kept. This cannot be undone.`
        }
        confirmLabel={sw ? "Futa" : "Delete"}
        onConfirm={() => confirmDelete && void remove(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />
    </>
  );
}
