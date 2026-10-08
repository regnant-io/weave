"use client";

import { useCallback, useEffect, useState } from "react";
import type { Language } from "@/lib/types";
import { fetchCatalog, formatTokens, type ModelCatalog } from "@/lib/models";

/**
 * Ollama endpoint + default model, live (no restart).
 *
 * The model list is normalised through `lib/models` before it reaches JSX. It
 * previously rendered the raw `{name, context}` object as a React child, which
 * is what crashed this page with minified React error #31.
 */
export default function OllamaSettings({ language }: { language: Language }) {
  const sw = language === "sw";
  const [host, setHost] = useState("");
  const [model, setModel] = useState("");
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (forceProbe = false) => {
    setRefreshing(forceProbe);
    setError(null);
    let cfg: { ollama_host?: unknown; ollama_model?: unknown } = {};
    try {
      const res = await fetch("/api/ollama-config", { cache: "no-store" });
      if (res.ok) cfg = await res.json();
    } catch {
      setError(sw ? "Imeshindwa kupakia mipangilio." : "Could not load the current configuration.");
    }
    const cat = await fetchCatalog(undefined, forceProbe);
    setHost(typeof cfg.ollama_host === "string" ? cfg.ollama_host : "");
    setModel(typeof cfg.ollama_model === "string" ? cfg.ollama_model : cat.currentModel);
    setCatalog(cat);
    setRefreshing(false);
  }, [sw]);

  useEffect(() => {
    void refresh(true);
  }, [refresh]);

  async function save() {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const res = await fetch("/api/ollama-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host, model }),
      });
      if (!res.ok) throw new Error(String(res.status));
      await refresh(true);
      setSaved(true);
      setTimeout(() => setSaved(false), 2200);
    } catch {
      setError(sw ? "Imeshindwa kuhifadhi." : "Could not save. Check the server URL.");
    } finally {
      setSaving(false);
    }
  }

  const models = catalog?.models ?? [];
  const selected = models.find((m) => m.name === model);
  const reachable = catalog?.ollamaReachable ?? models.length > 0;
  const active = catalog?.engine === "ollama";

  return (
    <section className="platform-panel p-4 sm:p-5">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">{sw ? "Modeli ya AI (Ollama)" : "AI model (Ollama)"}</h2>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] ${
            active ? "bg-ok-soft text-ok" : reachable ? "bg-accent-soft text-accent" : "bg-warn-soft text-warn"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${active ? "bg-ok" : reachable ? "bg-accent" : "bg-warn"}`} />
          {active ? sw ? "Inatumika" : "Active" : reachable ? sw ? "Imeunganishwa" : "Connected" : sw ? "Haipatikani" : "Offline"}
        </span>
      </div>
      <p className="mb-4 text-xs text-fg-faint">
        {sw
          ? "Unganisha seva ya Ollama na uchague modeli ya mazungumzo."
          : "Connect an Ollama server and choose a model for conversations."}
      </p>
      {!reachable && (
        <p className="mb-3 rounded-md border border-warn/20 bg-warn-soft px-3 py-2 text-xs leading-5 text-warn" role="status">
          {sw
            ? "Weave itatumia majibu ya msingi hadi seva na modeli zipatikane."
            : "Weave will use its local fallback until the server and a model are available."}
        </p>
      )}
      {reachable && !models.length && (
        <p className="mb-3 rounded-md border border-accent-line bg-accent-soft px-3 py-2 text-xs leading-5 text-accent-strong" role="status">
          {sw ? "Seva inajibu, lakini hakuna modeli iliyosakinishwa." : "The server responds, but no models are installed."}
        </p>
      )}

      <div className="space-y-3">
        <label className="block">
          <span className="text-xs text-fg-muted">{sw ? "Anwani ya Ollama" : "Ollama URL"}</span>
          <input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="http://localhost:11434"
            inputMode="url"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            className="mt-1 w-full rounded-sm border border-border bg-bg px-3 py-2 text-base outline-none transition-colors duration-fast focus:border-accent-line sm:text-sm"
          />
        </label>

        <label className="block">
          <span className="text-xs text-fg-muted">{sw ? "Modeli chaguo-msingi" : "Default model"}</span>
          {reachable ? (
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="mt-1 w-full rounded-sm border border-border bg-bg px-3 py-2 text-base outline-none transition-colors duration-fast focus:border-accent-line sm:text-sm"
            >
              {/* A saved model that is no longer on the server must stay
                  selectable, or saving would silently switch the user's model. */}
              {model && !models.some((m) => m.name === model) && (
                <option value={model}>{model} ({sw ? "haipo" : "not installed"})</option>
              )}
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {`${m.name}${m.context ? ` · ${formatTokens(m.context)}` : ""}${
                    m.supportsTools === true
                      ? sw ? " · zana" : " · tools"
                      : m.supportsTools === false
                        ? sw ? " · gumzo pekee" : " · chat only"
                        : " · ?"
                  }`}
                </option>
              ))}
            </select>
          ) : (
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="llama3.1"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className="mt-1 w-full rounded-sm border border-border bg-bg px-3 py-2 text-base outline-none transition-colors duration-fast focus:border-accent-line sm:text-sm"
            />
          )}
        </label>

        {selected?.supportsTools === false && (
          <p className="rounded-md border border-warn/20 bg-warn-soft px-3 py-2 text-xs leading-5 text-warn" role="status">
            {sw
              ? "Modeli hii haitoi uwezo wa kutumia zana. Uchambuzi wa data na utafutaji unaweza kukosa kufanya kazi."
              : "This model does not advertise tool support. Data analysis and retrieval may not work."}
          </p>
        )}
        {catalog?.modelSubstituted && (
          <p className="rounded-md border border-accent-line bg-accent-soft px-3 py-2 text-xs leading-5 text-accent-strong" role="status">
            {sw
              ? `Modeli ${catalog.configuredModel} haipo. Weave inatumia ${catalog.currentModel}.`
              : `The configured model ${catalog.configuredModel} is unavailable. Weave selected ${catalog.currentModel}.`}
          </p>
        )}

        {selected?.context ? (
          <p className="text-xs text-fg-faint">
            {sw ? "Dirisha la muktadha" : "Context window"}:{" "}
            <span className="font-mono text-fg-muted">{formatTokens(selected.context)}</span>
            {selected.trainedContext && selected.trainedContext > selected.context ? (
              <>
                {" "}
                <span className="text-warn">
                  ({sw ? "limepunguzwa kutoka" : "reduced from"} {formatTokens(selected.trainedContext)})
                </span>
              </>
            ) : null}
          </p>
        ) : null}

        {error && <p className="text-xs text-danger" role="alert">{error}</p>}

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button
            onClick={save}
            disabled={saving}
            className="platform-control platform-control-primary disabled:opacity-60"
          >
            {saving ? (sw ? "Inahifadhi…" : "Saving…") : sw ? "Hifadhi" : "Save"}
          </button>
          <button
            onClick={() => void refresh(true)}
            disabled={refreshing}
            className="platform-control disabled:cursor-wait disabled:opacity-60"
          >
            {refreshing ? sw ? "Inakagua…" : "Checking…" : sw ? "Jaribu muunganisho" : "Test connection"}
          </button>
          {saved && <span className="text-xs text-ok">{sw ? "Imehifadhiwa ✓" : "Saved ✓"}</span>}
        </div>
      </div>
    </section>
  );
}
