import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { api, ApiError } from "@/lib/api";
import { getLanguage, hasOnboarded, isAuthed } from "@/lib/session";
import { t } from "@/lib/i18n";
import CreateProjectForm from "@/components/CreateProjectForm";
import PageShell from "@/components/PageShell";
import ProjectList from "@/components/ProjectList";
import StatsPanel from "@/components/StatsPanel";
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

  // Analytics never block the page: `usageStats` swallows its own errors and
  // StatsPanel renders a quiet fallback for null.
  const stats = await api.usageStats();

  return (
    <PageShell size="wide">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="platform-eyebrow mb-2">WEAVE / WORKSPACE</p>
          <h1 className="platform-page-title text-[27px] font-semibold leading-tight sm:text-[32px]">
            {t("projects", language)}
          </h1>
          <p className="mt-2 max-w-2xl text-[13px] leading-5 text-fg-muted">
            {language === "sw"
              ? "Miradi yako ya utafiti na mazungumzo ya hivi karibuni."
              : "Research projects and their recent activity."}
          </p>
        </div>
        <CreateProjectForm language={language} defaultMode={defaultMode} />
      </div>

      <div className="mb-7 min-w-0">
        <StatsPanel stats={stats} language={language} />
      </div>

      <section aria-labelledby="project-section-title" className="min-w-0">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 id="project-section-title" className="text-sm font-semibold">
              {language === "sw" ? "Miradi" : "Projects"}
            </h2>
            <p className="mt-0.5 text-xs text-fg-faint">
              {language === "sw" ? "Hifadhi kazi zako katika nafasi tofauti." : "Keep related chats and datasets together."}
            </p>
          </div>
          <span className="font-mono text-[11px] text-fg-faint">{(stats?.projects ?? projects.length).toString().padStart(2, "0")}</span>
        </div>
        <ProjectList projects={projects} language={language} />
      </section>
    </PageShell>
  );
}
