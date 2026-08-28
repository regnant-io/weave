import { api } from "@/lib/api";
import { getLanguage } from "@/lib/session";
import { t } from "@/lib/i18n";
import LibrarySearchForm from "@/components/LibrarySearchForm";
import PageShell from "@/components/PageShell";
import type { Language, SourcePassage } from "@/lib/types";

// Anonymous browsing allowed (architecture 5.3).
export default async function LibraryPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const language = await getLanguage();
  const { q } = await searchParams;

  let results: SourcePassage[] = [];
  let sources: Awaited<ReturnType<typeof api.listSources>> = [];
  if (q) {
    results = (await api.searchLibrary(q, language)).results;
  } else {
    sources = await api.listSources();
  }

  return (
    <PageShell>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">{t("library", language)}</h1>
      <p className="mb-5 text-sm text-fg-muted">
        UDSM · COSTECH · NBS · {language === "sw" ? "majarida ya wazi" : "open journals"}
      </p>
      <LibrarySearchForm language={language} initial={q ?? ""} />

      {q ? (
        results.length === 0 ? (
          <p className="text-fg-muted">{language === "sw" ? "Hakuna matokeo." : "No results."}</p>
        ) : (
          <ul className="space-y-3">
            {results.map((r) => (
              <li key={r.chunk_id} className=" border border-border bg-surface p-4">
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <h2 className="font-semibold">{r.title}</h2>
                  <Badge status={r.access_status} predatory={r.predatory_flag} language={language} />
                  <span className="rounded-sm bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase text-fg-faint">{r.source_type}</span>
                </div>
                <p className="text-sm text-fg-muted">{r.content.slice(0, 260)}…</p>
                {r.url && (
                  <a href={r.url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-accent hover:underline">
                    {r.url}
                  </a>
                )}
              </li>
            ))}
          </ul>
        )
      ) : (
        <ul className="space-y-2">
          {sources.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-2 border border-border bg-surface px-4 py-3">
              <span className="text-sm">{s.title}</span>
              <Badge status={s.access_status} predatory={s.predatory_flag} language={language} />
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}

function Badge({ status, predatory, language }: { status: string; predatory: boolean; language: Language }) {
  return (
    <span className="flex gap-1">
      {status === "paywalled" ? (
        <span className="rounded-sm bg-warn/15 px-1.5 py-0.5 text-[10px] text-warn">{t("paywalled", language)}</span>
      ) : (
        <span className="rounded-sm bg-accent-soft px-1.5 py-0.5 text-[10px] text-accent">{t("open", language)}</span>
      )}
      {predatory && (
        <span className="rounded-sm bg-danger/15 px-1.5 py-0.5 text-[10px] text-danger">{t("predatory", language)}</span>
      )}
    </span>
  );
}
