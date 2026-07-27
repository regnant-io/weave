"use client";

import { useEffect, useState } from "react";
import type { Language } from "@/lib/types";

// Configurable Ollama endpoint + default model, live (no restart).
export default function OllamaSettings({ language }: { language: Language }) {
  const sw = language === "sw";
  const [host, setHost] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function refresh() {
    const [cfg, m] = await Promise.all([
      fetch("/api/ollama-config").then((r) => r.json()).catch(() => ({})),
      fetch("/api/models").then((r) => r.json()).catch(() => ({ models: [] })),
    ]);
    setHost(cfg.ollama_host ?? "");
    setModel(cfg.ollama_model ?? "");
    setModels(m.models ?? []);
  }
  useEffect(() => { refresh(); }, []);

  async function save() {
    setSaving(true); setSaved(false);
    await fetch("/api/ollama-config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host, model }),
    });
    await refresh();
    setSaving(false); setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <section className=" border border-border bg-surface p-5">
      <h2 className="mb-1 text-sm font-semibold">{sw ? "Modeli ya AI (Ollama)" : "AI model (Ollama)"}</h2>
      <p className="mb-4 text-xs text-fg-faint">
        {sw ? "Weka anwani ya seva ya Ollama na modeli chaguo-msingi." : "Set the Ollama server URL and default model."}
      </p>
      <div className="space-y-3">
        <label className="block">
          <span className="text-xs text-fg-muted">{sw ? "Anwani ya Ollama" : "Ollama URL"}</span>
          <input value={host} onChange={(e) => setHost(e.target.value)}
            placeholder="http://localhost:11434"
            className="mt-1 w-full border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-border-strong" />
        </label>
        <label className="block">
          <span className="text-xs text-fg-muted">{sw ? "Modeli chaguo-msingi" : "Default model"}</span>
          {models.length > 0 ? (
            <select value={model} onChange={(e) => setModel(e.target.value)}
              className="mt-1 w-full border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-border-strong">
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
              {model && !models.includes(model) && <option value={model}>{model}</option>}
            </select>
          ) : (
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="llama3.1"
              className="mt-1 w-full border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-border-strong" />
          )}
        </label>
        <div className="flex items-center gap-3">
          <button onClick={save} disabled={saving}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:opacity-90 disabled:opacity-60">
            {saving ? (sw ? "Inahifadhi…" : "Saving…") : (sw ? "Hifadhi" : "Save")}
          </button>
          {saved && <span className="text-xs text-accent">{sw ? "Imehifadhiwa ✓" : "Saved ✓"}</span>}
          <span className="text-xs text-fg-faint">{models.length} {sw ? "modeli" : "models"}</span>
        </div>
      </div>
    </section>
  );
}
