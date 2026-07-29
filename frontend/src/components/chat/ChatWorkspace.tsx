"use client";

import { useCallback, useEffect, useState } from "react";
import type { Dataset, Effort, Language, Message, Thread } from "@/lib/types";
import type { ServicePrefs } from "@/lib/services";
import ChatClient from "./ChatClient";
import ThreadBar from "./ThreadBar";

/**
 * Owns which chat is open and keeps the chat list in sync.
 *
 * Thread switching is client-side rather than a route change: the transcript is
 * the only thing that differs, and a full navigation would tear down the
 * composer, the panel dock and every panel width the user had set.
 *
 * `key={activeId}` on ChatClient is deliberate — switching chats must RESET the
 * streaming state, the block timeline and the artifact-dedup set. Trying to
 * reconcile all of that in place is exactly the kind of state bug that shows one
 * chat's charts inside another.
 */
export default function ChatWorkspace({
  projectId,
  language,
  mode,
  initialThreads,
  initialThreadId,
  initialMessages,
  datasets,
  lite,
  services,
  effort,
}: {
  projectId: string;
  language: Language;
  mode: string;
  initialThreads: Thread[];
  initialThreadId: string;
  initialMessages: Message[];
  datasets: Dataset[];
  lite: boolean;
  services: ServicePrefs;
  effort: Effort;
}) {
  const [threads, setThreads] = useState<Thread[]>(initialThreads);
  const [activeId, setActiveId] = useState<string>(initialThreadId);
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [loading, setLoading] = useState(false);

  const refreshThreads = useCallback(async () => {
    try {
      const res = await fetch(`/api/projects/${projectId}/threads`, { cache: "no-store" });
      if (!res.ok) return;
      const list: Thread[] = await res.json();
      setThreads(Array.isArray(list) ? list : []);
      // The active chat may have been deleted in another tab; fall back rather
      // than leaving the user typing into something that no longer exists.
      setActiveId((cur) => (list.some((t) => t.id === cur) ? cur : list[0]?.id ?? ""));
    } catch {
      /* the list is a convenience; a failed refresh must not break the chat */
    }
  }, [projectId]);

  const select = useCallback(
    async (id: string) => {
      if (!id || id === activeId) return;
      setActiveId(id);
      setLoading(true);
      try {
        const res = await fetch(`/api/projects/${projectId}/threads/${id}/messages`, {
          cache: "no-store",
        });
        setMessages(res.ok ? await res.json() : []);
      } catch {
        setMessages([]);
      } finally {
        setLoading(false);
      }
    },
    [activeId, projectId],
  );

  /** The server rolled this chat into a successor — follow it and reload. */
  const onThreadChange = useCallback(
    (id: string) => {
      void refreshThreads();
      void select(id);
    },
    [refreshThreads, select],
  );

  // Keep message counts and auto-generated titles current after a turn.
  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  return (
    <div className="relative h-full">
      <ThreadBar
        projectId={projectId}
        threads={threads}
        activeId={activeId}
        language={language}
        onSelect={select}
        onChanged={refreshThreads}
      />

      {loading ? (
        <div className="flex h-full items-center justify-center">
          <span className="pulse-dot h-2 w-2 rounded-full bg-accent" />
        </div>
      ) : (
        <ChatClient
          key={activeId || "none"}
          projectId={projectId}
          threadId={activeId || undefined}
          onThreadChange={onThreadChange}
          language={language}
          mode={mode}
          initialMessages={messages}
          datasets={datasets}
          lite={lite}
          services={services}
          effort={effort}
        />
      )}
    </div>
  );
}
