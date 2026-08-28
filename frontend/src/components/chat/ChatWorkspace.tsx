"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
 * `key` on ChatClient is deliberate — switching chats must RESET the streaming
 * state, the block timeline and the artifact-dedup set. Trying to reconcile all
 * of that in place is exactly the kind of state bug that shows one chat's charts
 * inside another.
 *
 * TRANSCRIPTS ARE CACHED PER THREAD, and that is what fixes two things at once:
 *
 *  - Switching used to blank the screen behind a spinner for a whole round trip
 *    every single time, including back to a chat read seconds earlier. A cached
 *    transcript renders immediately and is revalidated behind the scenes.
 *
 *  - A chat could come up EMPTY even though it had messages. The old state kept
 *    one `messages` array that was not tied to any particular thread, so any
 *    path that changed `activeId` without also resolving that thread's fetch —
 *    a rolled-over chat, a list refresh that dropped the active id, a switch
 *    whose request lost a race with a later one — mounted the transcript of one
 *    chat under the identity of another, or under nothing at all. Keying the
 *    cache by thread id makes that state unrepresentable: what renders is
 *    always what was fetched FOR the chat on screen.
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
  const [cache, setCache] = useState<Record<string, Message[]>>(() =>
    initialThreadId ? { [initialThreadId]: initialMessages } : {},
  );
  /**
   * Bumped only when a revalidation replaces a transcript the user is currently
   * looking at. It is part of ChatClient's key, so the remount is what makes a
   * late-arriving transcript actually appear — but see `applyFetched` for why
   * that is deliberately rare.
   */
  const [rev, setRev] = useState(0);

  /** Last request per thread, so a slow earlier response cannot overwrite a newer one. */
  const reqSeq = useRef<Record<string, number>>({});
  const inFlight = useRef<Set<string>>(new Set());

  const fetchMessages = useCallback(
    async (id: string): Promise<Message[] | null> => {
      try {
        const res = await fetch(`/api/projects/${projectId}/threads/${id}/messages`, {
          cache: "no-store",
        });
        if (!res.ok) return null;
        const list = await res.json();
        return Array.isArray(list) ? list : [];
      } catch {
        return null;
      }
    },
    [projectId],
  );

  /**
   * Mirror of `cache` for use outside render. State updaters must stay pure, so
   * the decision to remount is made here rather than inside one.
   */
  const cacheRef = useRef<Record<string, Message[]>>(cache);
  useEffect(() => {
    cacheRef.current = cache;
  }, [cache]);

  const applyFetched = useCallback((id: string, list: Message[], isActive: boolean) => {
    const had = cacheRef.current[id];
    if (had && had.length === list.length) return; // nothing new
    // Remounting the open chat throws away any turn in flight, so only do it
    // when the visible transcript is empty and the server has something to
    // show. That is exactly the "chat looks empty until I refresh" case, and
    // nothing is lost by remounting a transcript with no content in it.
    const wasBlank = !had || had.length === 0;
    cacheRef.current = { ...cacheRef.current, [id]: list };
    setCache(cacheRef.current);
    if (isActive && wasBlank && list.length > 0) setRev((r) => r + 1);
  }, []);

  const revalidate = useCallback(
    async (id: string, { active = false }: { active?: boolean } = {}) => {
      if (!id || inFlight.current.has(id)) return;
      inFlight.current.add(id);
      const seq = (reqSeq.current[id] ?? 0) + 1;
      reqSeq.current[id] = seq;
      try {
        const list = await fetchMessages(id);
        if (list && reqSeq.current[id] === seq) applyFetched(id, list, active);
      } finally {
        inFlight.current.delete(id);
      }
    },
    [applyFetched, fetchMessages],
  );

  const refreshThreads = useCallback(async () => {
    try {
      const res = await fetch(`/api/projects/${projectId}/threads`, { cache: "no-store" });
      if (!res.ok) return;
      const list: Thread[] = await res.json();
      if (!Array.isArray(list)) return;
      setThreads(list);
      // The active chat may have been deleted in another tab; fall back rather
      // than leaving the user typing into something that no longer exists.
      setActiveId((cur) => {
        if (list.some((t) => t.id === cur)) return cur;
        const next = list[0]?.id ?? "";
        if (next) void revalidate(next, { active: true });
        return next;
      });
    } catch {
      /* the list is a convenience; a failed refresh must not break the chat */
    }
  }, [projectId, revalidate]);

  const select = useCallback(
    (id: string) => {
      if (!id || id === activeId) return;
      setActiveId(id);
      // Cached transcripts appear instantly; uncached ones show ChatClient's own
      // empty state for the moment the request takes, which reads far better
      // than replacing the whole pane with a spinner.
      void revalidate(id, { active: true });
    },
    [activeId, revalidate],
  );

  /** Warm a transcript before it is asked for — switching then feels instant. */
  const prefetch = useCallback(
    (id: string) => {
      if (!id || cache[id] || inFlight.current.has(id)) return;
      void revalidate(id);
    },
    [cache, revalidate],
  );

  /** The server rolled this chat into a successor — follow it and reload. */
  const onThreadChange = useCallback(
    (id: string) => {
      void refreshThreads();
      select(id);
    },
    [refreshThreads, select],
  );

  // Keep message counts and auto-generated titles current, and make sure the
  // chat on screen matches the server even if SSR handed us a stale transcript.
  useEffect(() => {
    void refreshThreads();
    if (initialThreadId) void revalidate(initialThreadId, { active: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const messages = cache[activeId] ?? [];

  return (
    <div className="relative h-full">
      <ThreadBar
        projectId={projectId}
        threads={threads}
        activeId={activeId}
        language={language}
        onSelect={select}
        onPrefetch={prefetch}
        onChanged={refreshThreads}
      />

      <ChatClient
        key={`${activeId || "none"}:${rev}`}
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
    </div>
  );
}
