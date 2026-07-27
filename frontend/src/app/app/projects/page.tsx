import Link from "next/link";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { api, ApiError } from "@/lib/api";
import { getLanguage, hasOnboarded, isAuthed } from "@/lib/session";
import { t } from "@/lib/i18n";
import CreateProjectForm from "@/components/CreateProjectForm";
import PageShell from "@/components/PageShell";
import type { Mode } from "@/lib/types";

export default async function ProjectsPage() {
  if (!(await isAuthed())) redirect("/auth/login");
  // Projects is where every signed-in session lands, so it is the right gate for
  // first-run setup. Skipping onboarding sets the flag too, so this never loops.
  if (!(await hasOnboarded())) redirect("/onboarding");
  const language = await getLanguage();
  const modeCookie = (await cookies()).get("weave_mode")?.value;
  const defaultMode: Mode = modeCookie === "researcher" ? "researcher" : "student";

  let projects: Awaited<ReturnType<typeof api.listProjects>> = [];
  try {
    projects = await api.listProjects();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/auth/login");
    throw e;
  }

  return (
    <PageShell>
      <div className="mb-6 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t("projects", language)}</h1>
        <CreateProjectForm language={language} defaultMode={defaultMode} />
      </div>

      {projects.length === 0 ? (
        <div className=" border border-dashed border-border-strong p-10 text-center text-fg-muted">
          {language === "sw" ? "Huna miradi bado. Anzisha mradi mpya kuanza." : "No projects yet. Create one to get started."}
        </div>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/app/chat/${p.id}`}
                className="group block border border-border bg-surface p-4 transition-all hover:-translate-y-0.5 hover:border-border-strong hover:shadow-soft"
              >
                <div className="flex items-center justify-between gap-2">
                  <h2 className="truncate font-semibold">{p.title}</h2>
                  <span
                    className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
                      p.mode === "researcher" ? "bg-warn/15 text-warn" : "bg-accent-soft text-accent"
                    }`}
                  >
                    {t(p.mode, language)}
                  </span>
                </div>
                {p.summary && <p className="mt-2 line-clamp-2 text-sm text-fg-muted">{p.summary}</p>}
                <div className="mt-3 flex gap-3 text-xs text-accent">
                  <span>{t("chat", language)} →</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}
