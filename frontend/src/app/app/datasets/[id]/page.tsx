import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { getLanguage, isAuthed } from "@/lib/session";
import type { DatasetProfileColumn } from "@/lib/types";
import PageShell from "@/components/PageShell";

// Dataset profile view (architecture 4.2 /app/datasets/[id]): schema, stats.
export default async function DatasetPage({ params }: { params: Promise<{ id: string }> }) {
  if (!(await isAuthed())) redirect("/auth/login");
  const { id } = await params;
  const language = await getLanguage();

  try {
    const ds = await api.getDatasetProfile(id);
    const profile = ds.column_profile;
    const columns = profile.columns ?? [];

    // PageShell, not a bare div: `main` is `overflow-hidden`, so a page without
    // its own scroll container is simply cut off below the fold. It also
    // supplies the clearance for the fixed menu button.
    return (
      <PageShell>
        <h1 className="break-words text-2xl font-semibold tracking-tight">
          {ds.original_filename}
        </h1>
        <p className="mb-4 mt-1 text-sm text-fg-muted">
          {profile.row_count ?? ds.row_count ?? "?"} {language === "sw" ? "safu" : "rows"} ·{" "}
          {profile.column_count ?? columns.length} {language === "sw" ? "nguzo" : "columns"} ·{" "}
          {(ds.size_bytes / 1024).toFixed(1)} KB
        </p>

        {!profile.available ? (
          <p className="rounded bg-warn/10 p-3 text-sm text-warn">
            {language === "sw" ? "Wasifu haupatikani" : "Profile unavailable"}: {profile.reason}
          </p>
        ) : (
          <div className="overflow-x-auto rounded-sm border border-border bg-surface">
            <table className="min-w-full text-sm">
              <thead className="bg-surface-2 text-left text-xs uppercase text-fg-muted">
                <tr>
                  <th className="px-3 py-2">{language === "sw" ? "Nguzo" : "Column"}</th>
                  <th className="px-3 py-2">{language === "sw" ? "Aina" : "Type"}</th>
                  <th className="px-3 py-2">{language === "sw" ? "Zilizojaa" : "Non-null"}</th>
                  <th className="px-3 py-2">{language === "sw" ? "Kipekee" : "Unique"}</th>
                  <th className="px-3 py-2">{language === "sw" ? "Takwimu" : "Stats"}</th>
                </tr>
              </thead>
              <tbody>
                {columns.map((c: DatasetProfileColumn) => (
                  <tr key={c.name} className="border-t border-border">
                    <td className="px-3 py-2 font-medium">{c.name}</td>
                    <td className="px-3 py-2 text-fg-muted">{c.kind}</td>
                    <td className="px-3 py-2">{c.non_null}</td>
                    <td className="px-3 py-2">{c.unique}</td>
                    <td className="px-3 py-2 text-xs text-fg-muted">
                      {c.stats
                        ? `μ=${fmt(c.stats.mean)} σ=${fmt(c.stats.std)} [${fmt(c.stats.min)}, ${fmt(c.stats.max)}]`
                        : c.top_values
                          ? c.top_values.map((v) => `${v.value}(${v.count})`).join(", ")
                          : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageShell>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/auth/login");
    if (e instanceof ApiError && e.status === 404) {
      return <p className="py-8 text-center text-fg-muted">Dataset not found.</p>;
    }
    throw e;
  }
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Math.abs(n) >= 1000 ? n.toFixed(0) : n.toFixed(2);
}
