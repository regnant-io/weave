"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Language } from "@/lib/types";

interface Hyp { id?: string; text_sw?: string; text_en?: string; status?: string }
interface Note { id: string; text: string; created_at: string }

export default function ProjectMemoryClient({
  projectId, language, hypotheses, notes, summary,
}: {
  projectId: string; language: Language; hypotheses: Hyp[]; notes: Note[]; summary: string;
}) {
  const router = useRouter();
  const sw = language === "sw";
  const [newHyp, setNewHyp] = useState("");
  const [newNote, setNewNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function call(action: string, method: string, body?: object) {
    setBusy(true);
    await fetch(`/api/projects/${projectId}/${action}`, {
      method, headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    setBusy(false);
    router.refresh();
  }

  const cycle = (s?: string) => (s === "open" ? "supported" : s === "supported" ? "refuted" : "open");

  return (
    <div className="space-y-6">
      {/* hypotheses */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-fg-faint">
          {sw ? "Dhana za utafiti" : "Hypotheses"}
        </h2>
        <ul className="space-y-2">
          {hypotheses.map((h, i) => (
            <li key={h.id ?? i} className="flex items-center gap-2 border border-border bg-surface p-3 text-sm">
              <button onClick={() => h.id && call(`hypotheses/${h.id}`, "PATCH", { status: cycle(h.status) })}
                className={`rounded-full px-2 py-0.5 text-[11px] ${h.status === "supported" ? "bg-accent-soft text-accent" : h.status === "refuted" ? "bg-danger/15 text-danger" : "bg-surface-2 text-fg-muted"}`}>
                {h.status ?? "open"}
              </button>
              <span className="flex-1">{(sw ? h.text_sw : h.text_en) || h.text_en || h.text_sw}</span>
              {h.id && <button onClick={() => call(`hypotheses/${h.id}`, "DELETE")} className="text-fg-faint hover:text-danger">✕</button>}
            </li>
          ))}
          {hypotheses.length === 0 && <li className=" border border-dashed border-border-strong p-3 text-center text-sm text-fg-faint">{sw ? "Hakuna dhana bado." : "No hypotheses yet."}</li>}
        </ul>
        <div className="mt-2 flex gap-2">
          <input value={newHyp} onChange={(e) => setNewHyp(e.target.value)} placeholder={sw ? "Ongeza dhana…" : "Add a hypothesis…"}
            className="flex-1 border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-border-strong" />
          <button disabled={busy || !newHyp.trim()} onClick={() => { call("hypotheses", "POST", sw ? { text_sw: newHyp, status: "open" } : { text_en: newHyp, status: "open" }); setNewHyp(""); }}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:opacity-90 disabled:opacity-50">+</button>
        </div>
      </section>

      {/* notes */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-fg-faint">{sw ? "Maelezo (mapitio)" : "Lit-review notes"}</h2>
        <ul className="space-y-2">
          {notes.map((n) => (
            <li key={n.id} className=" border border-border bg-surface p-3 text-sm">{n.text}</li>
          ))}
          {notes.length === 0 && <li className=" border border-dashed border-border-strong p-3 text-center text-sm text-fg-faint">{sw ? "Hakuna maelezo." : "No notes yet."}</li>}
        </ul>
        <div className="mt-2 flex gap-2">
          <input value={newNote} onChange={(e) => setNewNote(e.target.value)} placeholder={sw ? "Ongeza maelezo…" : "Add a note…"}
            className="flex-1 border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-border-strong" />
          <button disabled={busy || !newNote.trim()} onClick={() => { call("notes", "POST", { text: newNote }); setNewNote(""); }}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:opacity-90 disabled:opacity-50">+</button>
        </div>
      </section>

      {/* summary */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-faint">{sw ? "Muhtasari" : "Summary"}</h2>
          <button disabled={busy} onClick={() => call("summarize", "POST")}
            className="rounded-sm border border-border px-2.5 py-1 text-xs text-fg-muted hover:bg-surface-hover hover:text-fg disabled:opacity-50">
            ↻ {sw ? "Zalisha upya" : "Regenerate"}
          </button>
        </div>
        <p className="whitespace-pre-wrap border border-border bg-surface p-3 text-sm text-fg-muted">
          {summary || (sw ? "Hakuna muhtasari bado." : "No summary yet.")}
        </p>
      </section>
    </div>
  );
}
