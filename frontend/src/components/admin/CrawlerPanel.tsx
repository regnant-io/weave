"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Operator surface for the crawler.
 *
 * Two lists, because they need different actions. Curated seeds are things an
 * operator deliberately added and can run. Session-discovered seeds are domains
 * real conversations consulted — they arrive DISABLED and crawl nothing until
 * someone approves them here, which is what stops one odd link in one chat from
 * starting a crawl of the open web.
 *
 * The page log shows refusals as well as successes on purpose: "why is this
 * page not in the library" is the question an operator actually has, and
 * "disallowed by robots.txt" is only answerable if the refusal was recorded.
 */

type Seed = {
  id: string;
  url: string;
  domain: string;
  source_type: string;
  language: string;
  origin: "admin" | "session";
  enabled: boolean;
  max_depth: number;
  max_pages: number;
  delay_seconds: number;
  same_domain_only: boolean;
  render_js: boolean;
  status: string;
  last_error: string;
  pages_fetched: number;
  pages_indexed: number;
  pages_recorded: number;
  last_run_at: string | null;
};

type Page = {
  id: string;
  url: string;
  depth: number;
  status: string;
  reason: string;
  title: string;
  chars: number;
};

const STATUS_TONE: Record<string, string> = {
  indexed: "text-accent",
  error: "text-danger",
  running: "text-accent",
  done: "text-fg-muted",
  pending: "text-fg-faint",
};

export default function CrawlerPanel() {
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const [pages, setPages] = useState<Record<string, Page[]>>({});
  const [open, setOpen] = useState<string>("");
  const [busy, setBusy] = useState<string>("");
  const [msg, setMsg] = useState("");

  const [url, setUrl] = useState("");
  const [sourceType, setSourceType] = useState("gov");
  const [language, setLanguage] = useState("en");
  const [maxDepth, setMaxDepth] = useState(2);
  const [maxPages, setMaxPages] = useState(40);
  const [delay, setDelay] = useState(1);
  const [renderJs, setRenderJs] = useState(false);

  const load = useCallback(async () => {
    const list = await fetch("/api/admin/crawl/seeds", { cache: "no-store" })
      .then((r) => r.json())
      .catch(() => []);
    setSeeds(Array.isArray(list) ? list : []);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // A crawl is deliberately slow — it waits between requests to be polite — so
  // the only honest progress indicator is a poll while something is running.
  useEffect(() => {
    if (!seeds.some((s) => s.status === "running")) return;
    const t = setInterval(() => void load(), 4000);
    return () => clearInterval(t);
  }, [seeds, load]);

  async function addSeed() {
    if (!url.trim()) return;
    setBusy("add");
    setMsg("");
    const r = await fetch("/api/admin/crawl/seeds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        source_type: sourceType,
        language,
        max_depth: maxDepth,
        max_pages: maxPages,
        delay_seconds: delay,
        render_js: renderJs,
      }),
    });
    const d = await r.json().catch(() => ({}));
    setBusy("");
    setMsg(d.error ?? `Added ${d.seed?.domain ?? url}`);
    if (!d.error) setUrl("");
    void load();
  }

  async function patchSeed(id: string, body: Record<string, unknown>) {
    setBusy(id);
    await fetch(`/api/admin/crawl/seeds/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => null);
    setBusy("");
    void load();
  }

  async function runSeed(id: string) {
    setBusy(id);
    setMsg("");
    const r = await fetch(`/api/admin/crawl/seeds/${id}/run`, { method: "POST" });
    const d = await r.json().catch(() => ({}));
    setBusy("");
    setMsg(d.error ?? "Crawl started — this runs slowly on purpose.");
    void load();
  }

  async function removeSeed(id: string) {
    setBusy(id);
    await fetch(`/api/admin/crawl/seeds/${id}`, { method: "DELETE" }).catch(() => null);
    setBusy("");
    void load();
  }

  async function togglePages(id: string) {
    if (open === id) {
      setOpen("");
      return;
    }
    setOpen(id);
    if (!pages[id]) {
      const rows = await fetch(`/api/admin/crawl/seeds/${id}/pages?limit=120`, {
        cache: "no-store",
      })
        .then((r) => r.json())
        .catch(() => []);
      setPages((cur) => ({ ...cur, [id]: Array.isArray(rows) ? rows : [] }));
    }
  }

  const curated = seeds.filter((s) => s.origin === "admin");
  const discovered = seeds.filter((s) => s.origin === "session");

  return (
    <div className="space-y-6">
      {/* -- add a seed -------------------------------------------------- */}
      <section className="border border-border bg-surface p-4">
        <h3 className="text-sm font-semibold">Add a crawl seed</h3>
        <p className="mt-1 text-xs leading-relaxed text-fg-muted">
          The crawler obeys robots.txt, waits between requests, and identifies itself as
          WeaveBot. Keep the delay at 1s or more for small institutional servers.
        </p>

        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.nbs.go.tz/"
            className="min-w-[16rem] flex-1 border border-border bg-bg px-3 py-2 text-[16px] outline-none focus:border-accent-line sm:text-[13px]"
          />
          <select
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
            className="border border-border bg-bg px-2 py-2 text-[13px]"
          >
            {["gov", "nbs", "udsm", "costech", "journal", "web"].map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="border border-border bg-bg px-2 py-2 text-[13px]"
          >
            <option value="en">en</option>
            <option value="sw">sw</option>
          </select>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-fg-muted">
          <label className="flex items-center gap-1.5">
            depth
            <input
              type="number" min={0} max={5} value={maxDepth}
              onChange={(e) => setMaxDepth(Number(e.target.value))}
              className="w-14 border border-border bg-bg px-2 py-1 text-[13px]"
            />
          </label>
          <label className="flex items-center gap-1.5">
            max pages
            <input
              type="number" min={1} max={500} value={maxPages}
              onChange={(e) => setMaxPages(Number(e.target.value))}
              className="w-20 border border-border bg-bg px-2 py-1 text-[13px]"
            />
          </label>
          <label className="flex items-center gap-1.5">
            delay (s)
            <input
              type="number" min={0.5} step={0.5} value={delay}
              onChange={(e) => setDelay(Number(e.target.value))}
              className="w-16 border border-border bg-bg px-2 py-1 text-[13px]"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox" checked={renderJs}
              onChange={(e) => setRenderJs(e.target.checked)}
            />
            render JS (slower)
          </label>
          <button
            onClick={addSeed}
            disabled={busy === "add" || !url.trim()}
            className="border border-accent bg-accent px-3 py-1.5 text-[13px] text-white disabled:opacity-50"
          >
            {busy === "add" ? "Adding…" : "Add seed"}
          </button>
        </div>

        {msg && <p className="mt-2 text-xs text-fg-muted">{msg}</p>}
      </section>

      <SeedList
        title="Curated seeds"
        blurb="Added by an operator. Run one to crawl it now."
        seeds={curated}
        busy={busy}
        open={open}
        pages={pages}
        onRun={runSeed}
        onPatch={patchSeed}
        onRemove={removeSeed}
        onTogglePages={togglePages}
      />

      <SeedList
        title="Discovered from sessions"
        blurb="Domains real conversations consulted. They arrive disabled and crawl nothing until you enable them. Users can switch this off in their own Settings."
        seeds={discovered}
        busy={busy}
        open={open}
        pages={pages}
        onRun={runSeed}
        onPatch={patchSeed}
        onRemove={removeSeed}
        onTogglePages={togglePages}
      />
    </div>
  );
}

function SeedList({
  title, blurb, seeds, busy, open, pages, onRun, onPatch, onRemove, onTogglePages,
}: {
  title: string;
  blurb: string;
  seeds: Seed[];
  busy: string;
  open: string;
  pages: Record<string, Page[]>;
  onRun: (id: string) => void;
  onPatch: (id: string, body: Record<string, unknown>) => void;
  onRemove: (id: string) => void;
  onTogglePages: (id: string) => void;
}) {
  return (
    <section>
      <h3 className="text-sm font-semibold">
        {title} <span className="font-mono text-xs text-fg-faint">{seeds.length}</span>
      </h3>
      <p className="mt-1 max-w-[70ch] text-xs leading-relaxed text-fg-muted">{blurb}</p>

      {seeds.length === 0 ? (
        <p className="mt-3 border border-dashed border-border px-3 py-4 text-xs text-fg-faint">
          Nothing here yet.
        </p>
      ) : (
        <div className="mt-3 space-y-2">
          {seeds.map((s) => (
            <div key={s.id} className="border border-border bg-surface">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5">
                <span className="min-w-0 flex-1 truncate text-[13px]">{s.domain}</span>
                <span className={`font-mono text-[11px] ${STATUS_TONE[s.status] ?? "text-fg-faint"}`}>
                  {s.status}
                </span>
                <span className="font-mono text-[11px] text-fg-faint">
                  d{s.max_depth} · {s.max_pages}p · {s.delay_seconds}s
                  {s.render_js ? " · js" : ""}
                </span>
                <span className="font-mono text-[11px] text-fg-muted">
                  {s.pages_indexed} indexed / {s.pages_fetched} fetched
                </span>

                <label className="flex items-center gap-1 text-[11px] text-fg-muted">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    disabled={busy === s.id}
                    onChange={(e) => onPatch(s.id, { enabled: e.target.checked })}
                  />
                  enabled
                </label>
                <button
                  onClick={() => onRun(s.id)}
                  disabled={busy === s.id || !s.enabled || s.status === "running"}
                  className="border border-border px-2 py-1 text-[11px] hover:border-accent hover:text-accent disabled:opacity-40"
                >
                  Run
                </button>
                <button
                  onClick={() => onTogglePages(s.id)}
                  className="border border-border px-2 py-1 text-[11px] hover:border-accent hover:text-accent"
                >
                  {open === s.id ? "Hide log" : `Log (${s.pages_recorded})`}
                </button>
                <button
                  onClick={() => onRemove(s.id)}
                  disabled={busy === s.id}
                  className="border border-border px-2 py-1 text-[11px] text-fg-faint hover:border-danger hover:text-danger disabled:opacity-40"
                >
                  Delete
                </button>
              </div>

              {s.last_error && (
                <p className="border-t border-border px-3 py-1.5 text-[11px] text-danger">
                  {s.last_error}
                </p>
              )}

              {open === s.id && (
                <div className="max-h-72 overflow-auto border-t border-border">
                  {(pages[s.id] ?? []).length === 0 ? (
                    <p className="px-3 py-3 text-[11px] text-fg-faint">
                      No pages recorded yet.
                    </p>
                  ) : (
                    <table className="w-full text-[11px]">
                      <tbody>
                        {(pages[s.id] ?? []).map((p) => (
                          <tr key={p.id} className="border-b border-border/60 last:border-b-0">
                            <td className="px-3 py-1.5 font-mono text-fg-faint">d{p.depth}</td>
                            <td
                              className={`whitespace-nowrap px-2 py-1.5 font-mono ${
                                p.status === "indexed"
                                  ? "text-accent"
                                  : p.status === "error"
                                    ? "text-danger"
                                    : "text-fg-faint"
                              }`}
                            >
                              {p.status}
                            </td>
                            <td className="max-w-[26rem] truncate px-2 py-1.5">
                              {p.title || p.url}
                            </td>
                            <td className="px-2 py-1.5 text-fg-muted">{p.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
