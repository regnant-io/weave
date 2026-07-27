"use client";

import { useEffect, useState } from "react";

type Stats = Record<string, number>;
type Source = { id: string; title: string; url: string | null; source_type: string; chunks: number; predatory_flag: boolean; ingested_at: string | null };
type Audit = { id: string; status: string; code_hash: string; execution_time_ms: number; created_at: string | null };

export default function AdminClient() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [forbidden, setForbidden] = useState(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    const s = await fetch("/api/admin/stats");
    if (s.status === 403) { setForbidden(true); return; }
    setStats(await s.json().catch(() => null));
    setSources(await fetch("/api/admin/sources").then((r) => r.json()).catch(() => []));
    setAudit(await fetch("/api/admin/audit?limit=25").then((r) => r.json()).catch(() => []));
  }
  useEffect(() => { load(); }, []);

  async function ingest() {
    if (!url.trim()) return;
    setBusy(true); setMsg("");
    const r = await fetch("/api/admin/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    setMsg(d.ingested ? `Ingested "${d.title}" (${d.chunks} chunks)` : (d.error ?? "done"));
    setUrl("");
    load();
  }

  if (forbidden) {
    return <p className=" border border-warn/30 bg-warn/10 px-4 py-3 text-sm text-warn">
      Admin access required (institutional / admin role).
    </p>;
  }

  return (
    <div className="space-y-6">
      {/* stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats && Object.entries(stats).map(([k, v]) => (
          <div key={k} className=" border border-border bg-surface p-4">
            <div className="text-2xl font-semibold">{v}</div>
            <div className="text-xs text-fg-muted">{k.replace(/_/g, " ")}</div>
          </div>
        ))}
      </div>

      {/* ingest */}
      <section className=" border border-border bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold">Ingest a source</h2>
        <div className="flex gap-2">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… (HTML or PDF)"
            className="flex-1 border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-border-strong" />
          <button onClick={ingest} disabled={busy}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:opacity-90 disabled:opacity-60">
            {busy ? "Ingesting…" : "Ingest"}
          </button>
        </div>
        {msg && <p className="mt-2 text-xs text-accent">{msg}</p>}
      </section>

      {/* sources */}
      <section className=" border border-border bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold">Source library ({sources.length})</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase text-fg-faint">
              <tr><th className="py-1 pr-3">Title</th><th className="pr-3">Type</th><th className="pr-3">Chunks</th><th>Flag</th></tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.id} className="border-t border-border">
                  <td className="max-w-[22rem] truncate py-1.5 pr-3">{s.title}</td>
                  <td className="pr-3 text-fg-muted">{s.source_type}</td>
                  <td className="pr-3">{s.chunks}</td>
                  <td>{s.predatory_flag ? <span className="text-danger">⚑</span> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* sandbox audit */}
      <section className=" border border-border bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold">Sandbox audit log</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase text-fg-faint">
              <tr><th className="py-1 pr-3">Status</th><th className="pr-3">Code hash</th><th className="pr-3">ms</th><th>When</th></tr>
            </thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id} className="border-t border-border">
                  <td className="py-1.5 pr-3"><span className={a.status === "ok" ? "text-accent" : "text-warn"}>{a.status}</span></td>
                  <td className="pr-3 font-mono text-xs text-fg-muted">{a.code_hash}</td>
                  <td className="pr-3">{a.execution_time_ms}</td>
                  <td className="text-xs text-fg-faint">{a.created_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
              {audit.length === 0 && <tr><td colSpan={4} className="py-3 text-fg-faint">No executions yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
