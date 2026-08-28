import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { getEffort, getLanguage, getLiteMode, getServices, isAuthed } from "@/lib/session";
import type { Effort, Message, Thread } from "@/lib/types";
import ChatWorkspace from "@/components/chat/ChatWorkspace";
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
    const [project, datasets, threads] = await Promise.all([
      api.getProject(projectId),
      api.listProjectDatasets(projectId),
      // The threads endpoint creates a first thread on demand, so a brand-new
      // project always has somewhere to type.
      api.listThreads(projectId).catch((): Thread[] => []),
    ]);

    // Most recently updated chat first, which is where the user left off.
    const activeThread = threads[0];
    let messages: Message[] = [];
    if (activeThread) {
      messages = await api.getThreadMessages(projectId, activeThread.id).catch(() => []);
    } else {
      // Pre-thread project whose backfill has not run: fall back to the flat
      // project message list rather than showing an empty conversation.
      messages = await api.getMessages(projectId).catch(() => []);
    }

    return (
      <div className="h-full">
        <SetSidebarProject project={{ id: projectId, title: project.title, mode: project.mode }} />
        <ChatWorkspace
          projectId={projectId}
          language={language}
          mode={project.mode}
          initialThreads={threads}
          initialThreadId={activeThread?.id ?? ""}
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
