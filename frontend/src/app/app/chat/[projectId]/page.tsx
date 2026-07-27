import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { getEffort, getLanguage, getLiteMode, getServices, isAuthed } from "@/lib/session";
import type { Effort } from "@/lib/types";
import ChatClient from "@/components/chat/ChatClient";
import { SetSidebarProject } from "@/components/shell/SidebarContext";

export default async function ChatPage({ params }: { params: Promise<{ projectId: string }> }) {
  if (!(await isAuthed())) redirect("/auth/login");
  const { projectId } = await params;
  const [language, lite, services, effort] = await Promise.all([
    getLanguage(),
    getLiteMode(),
    getServices(),
    getEffort(),
  ]);

  try {
    const [project, messages, datasets] = await Promise.all([
      api.getProject(projectId),
      api.getMessages(projectId),
      api.listProjectDatasets(projectId),
    ]);

    return (
      <div className="h-full">
        <SetSidebarProject project={{ id: projectId, title: project.title, mode: project.mode }} />
        <ChatClient
          projectId={projectId}
          language={language}
          mode={project.mode}
          initialMessages={messages}
          datasets={datasets}
          lite={lite}
          services={services}
          effort={effort as Effort}
        />
      </div>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/auth/login");
    if (e instanceof ApiError && e.status === 404) {
      return <p className="py-16 text-center text-fg-muted">Project not found.</p>;
    }
    throw e;
  }
}
