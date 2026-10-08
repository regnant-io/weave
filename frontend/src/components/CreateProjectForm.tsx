"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Language, Mode } from "@/lib/types";
import { t } from "@/lib/i18n";

export default function CreateProjectForm({ language, defaultMode }: { language: Language; defaultMode: Mode }) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<Mode>(defaultMode);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setLoading(true);
    const res = await fetch("/api/projects/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, mode }),
    });
    setLoading(false);
    if (res.ok) {
      const p = await res.json();
      router.push(`/app/chat/${p.id}`);
      router.refresh();
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="platform-control platform-control-primary inline-flex items-center gap-2"
      >
        <span aria-hidden="true" className="font-mono text-base leading-none">+</span>
        {t("newProject", language)}
      </button>
    );
  }

  return (
    <form onSubmit={create} className="platform-panel w-full max-w-sm p-4 shadow-soft">
      <label htmlFor="project-title" className="mb-1.5 block text-xs font-medium text-fg-muted">
        {language === "sw" ? "Jina la mradi" : "Project name"}
      </label>
      <input
        id="project-title"
        autoFocus
        required
        maxLength={255}
        className="mb-3 min-h-10 w-full rounded-md border border-border bg-bg px-3 py-2 text-sm outline-none transition-colors focus:border-accent"
        placeholder={language === "sw" ? "Jina la mradi" : "Project title"}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <div className="mb-3 inline-flex rounded-md border border-border bg-surface-2 p-0.5">
        {(["student", "researcher"] as Mode[]).map((m) => (
          <button
            type="button"
            key={m}
            onClick={() => setMode(m)}
            aria-pressed={mode === m}
            className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
              mode === m ? "bg-surface text-fg shadow-sm" : "text-fg-muted hover:text-fg"
            }`}
          >
            {t(m, language)}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          disabled={loading}
          className="platform-control platform-control-primary disabled:cursor-wait disabled:opacity-60"
        >
          {loading ? (language === "sw" ? "Inaunda…" : "Creating…") : t("newProject", language)}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="platform-control">
          {language === "sw" ? "Ghairi" : "Cancel"}
        </button>
      </div>
    </form>
  );
}
