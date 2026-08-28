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
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t("projects", language)}</h1>
        <CreateProjectForm language={language} defaultMode={defaultMode} />
      </div>

      {/*
        Analytics sit top-right on desktop and BELOW the projects on mobile:
        the projects are what the user came for, and a 400px stats block above
        them on a phone would bury the actual content.
      */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
        <div className="order-1 min-w-0">
          <ProjectList projects={projects} language={language} />
        </div>
        <div className="order-2 min-w-0 lg:sticky lg:top-4">
          <StatsPanel stats={stats} language={language} />
        </div>
      </div>
    </PageShell>
  );
}
