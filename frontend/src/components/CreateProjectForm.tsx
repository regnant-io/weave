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
        className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-fg transition-opacity hover:opacity-90"
      >
        + {t("newProject", language)}
      </button>
    );
  }

  return (
    <form onSubmit={create} className="w-full max-w-sm border border-border bg-surface p-4 shadow-soft">
      <input
        autoFocus
        className="mb-3 w-full border border-border bg-bg px-3 py-2 outline-none focus:border-border-strong"
        placeholder={language === "sw" ? "Jina la mradi" : "Project title"}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <div className="mb-3 inline-flex rounded-full border border-border bg-surface-2 p-0.5">
        {(["student", "researcher"] as Mode[]).map((m) => (
          <button
            type="button"
            key={m}
            onClick={() => setMode(m)}
            className={`rounded-full px-3 py-1.5 text-sm transition-colors ${
              mode === m ? "bg-accent text-accent-fg" : "text-fg-muted hover:text-fg"
            }`}
          >
            {t(m, language)}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          disabled={loading}
          className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
        >
          {t("newProject", language)}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded-full px-4 py-2 text-sm text-fg-muted hover:bg-surface-hover">
          {language === "sw" ? "Ghairi" : "Cancel"}
        </button>
      </div>
    </form>
  );
}
