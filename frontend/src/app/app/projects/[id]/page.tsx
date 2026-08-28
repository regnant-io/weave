import Link from "next/link";
import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { getLanguage, isAuthed } from "@/lib/session";
import { t } from "@/lib/i18n";
import PageShell from "@/components/PageShell";
import ProjectMemoryClient from "@/components/ProjectMemoryClient";

// Persistent research memory (architecture 4.2 /app/projects/[id]).
export default async function ProjectMemoryPage({ params }: { params: Promise<{ id: string }> }) {
  if (!(await isAuthed())) redirect("/auth/login");
  const { id } = await params;
  const language = await getLanguage();

  try {
    const [project, datasets] = await Promise.all([
      api.getProject(id),
      api.listProjectDatasets(id),
    ]);

    return (
      <PageShell>
        <div className="mb-5 flex items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{project.title}</h1>
          <Link href={`/app/chat/${id}`} className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:opacity-90">
            {t("chat", language)} →
          </Link>
        </div>

        <ProjectMemoryClient
          projectId={id}
          language={language}
          hypotheses={(project.hypotheses || {}) as never}
          notes={project.notes ?? []}
          summary={project.summary}
        />

        <section className="mt-8">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-fg-faint">{t("datasets", language)}</h2>
          {datasets.length === 0 ? (
            <p className=" border border-dashed border-border-strong p-4 text-center text-sm text-fg-faint">
              {language === "sw" ? "Hakuna data." : "No datasets."}
            </p>
          ) : (
            <ul className="space-y-2">
              {datasets.map((d) => (
                <li key={d.id}>
                  <Link href={`/app/datasets/${d.id}`}
                    className="flex items-center justify-between border border-border bg-surface p-3 text-sm hover:border-border-strong">
                    <span>{d.original_filename}</span>
                    <span className="text-xs text-fg-faint">{d.row_count ?? "?"} {language === "sw" ? "safu" : "rows"} · {d.status}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </PageShell>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/auth/login");
    throw e;
  }
}
