"use client";

import { useEffect, useState } from "react";
import CrawlerPanel from "./admin/CrawlerPanel";

type Stats = Record<string, number>;
type Source = { id: string; title: string; url: string | null; source_type: string; chunks: number; predatory_flag: boolean; ingested_at: string | null };
type Audit = { id: string; status: string; code_hash: string; execution_time_ms: number; created_at: string | null };
type Job = { id: string; kind: string; status: string; attempts: number; error: string; updated_at: string | null };
type Metrics = {
  runtime: Record<string, { count?: number; duration_ms_sum?: number }>;
  jobs: Record<string, number>;
  outbox: Record<string, number>;
};

export default function AdminClient() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
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
    setJobs(await fetch("/api/admin/jobs?limit=25").then((r) => r.json()).catch(() => []));
    setMetrics(await fetch("/api/admin/metrics").then((r) => r.json()).catch(() => null));
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

      {/* durable control-plane health */}
      <section className="border border-border bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold">Operations</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(metrics?.jobs ?? {}).map(([state, count]) => (
            <div key={`job-${state}`} className="border border-border p-3">
              <div className="text-xl font-semibold">{count}</div>
              <div className="text-xs text-fg-muted">jobs · {state}</div>
            </div>
          ))}
          {Object.entries(metrics?.outbox ?? {}).map(([state, count]) => (
            <div key={`outbox-${state}`} className="border border-border p-3">
              <div className="text-xl font-semibold">{count}</div>
              <div className="text-xs text-fg-muted">delivery · {state}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase text-fg-faint">
              <tr><th className="py-1 pr-3">Job</th><th className="pr-3">State</th><th className="pr-3">Attempts</th><th>Last error</th></tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id} className="border-t border-border">
                  <td className="py-1.5 pr-3 font-mono text-xs">{j.kind.replace("weave.", "")}</td>
                  <td className={j.status === "succeeded" ? "pr-3 text-ok" : j.status === "dead_letter" || j.status === "failed" ? "pr-3 text-danger" : "pr-3 text-warn"}>{j.status}</td>
                  <td className="pr-3">{j.attempts}</td>
                  <td className="max-w-[24rem] truncate text-xs text-fg-muted" title={j.error}>{j.error || "—"}</td>
                </tr>
              ))}
              {jobs.length === 0 && <tr><td colSpan={4} className="py-3 text-fg-faint">No background jobs yet.</td></tr>}
            </tbody>
          </table>
        </div>
        {metrics && Object.keys(metrics.runtime).length > 0 && (
          <details className="mt-4 border-t border-border pt-3">
            <summary className="cursor-pointer text-xs font-medium text-fg-muted">Runtime counters ({Object.keys(metrics.runtime).length})</summary>
            <div className="mt-2 grid gap-1 font-mono text-xs text-fg-muted">
              {Object.entries(metrics.runtime).map(([name, value]) => (
                <div key={name}>{name}: {value.count ?? 0} calls · {Math.round(value.duration_ms_sum ?? 0)} ms total</div>
              ))}
            </div>
          </details>
        )}
      </section>

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

      {/* automated ingestion — crawlers and scrapers */}
      <section className=" border border-border bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold">Automated ingestion</h2>
        <CrawlerPanel />
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
