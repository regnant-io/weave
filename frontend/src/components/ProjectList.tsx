"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import type { Language, Project } from "@/lib/types";
import { t } from "@/lib/i18n";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { IcoCheck, IcoClose, IcoEdit, IcoMore, IcoTrash } from "@/components/ui/icons";

/**
 * Projects, with the CRUD that was missing.
 *
 * Deleting a project destroys its chats, datasets, generated artifacts and the
 * on-disk workspace, so both destructive paths are gated: a single delete needs
 * a confirmation naming the project, and "delete all" additionally requires the
 * word DELETE to be typed. A button alone is far too easy to press twice.
 */
export default function ProjectList({
  projects: initial,
  language,
}: {
  projects: Project[];
  language: Language;
}) {
  const sw = language === "sw";
  const router = useRouter();
  const [projects, setProjects] = useState(initial);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmOne, setConfirmOne] = useState<Project | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreProjects, setMoreProjects] = useState(initial.length >= 100);

  const refresh = useCallback(() => router.refresh(), [router]);

  async function rename(p: Project) {
    const title = draft.trim();
    setRenaming(null);
    if (!title || title === p.title) return;
    // Optimistic: the list is the user's own data and a rename is trivially
    // reversible, so waiting on a round-trip only makes it feel slow.
    setProjects((prev) => prev.map((x) => (x.id === p.id ? { ...x, title } : x)));
    try {
      const res = await fetch(`/api/projects/${p.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) throw new Error();
      refresh();
    } catch {
      setProjects((prev) => prev.map((x) => (x.id === p.id ? { ...x, title: p.title } : x)));
      setError(sw ? "Imeshindwa kubadilisha jina." : "Could not rename that project.");
    }
  }

  async function removeOne(p: Project) {
    setConfirmOne(null);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${p.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setProjects((prev) => prev.filter((x) => x.id !== p.id));
      refresh();
    } catch {
      setError(sw ? "Imeshindwa kufuta mradi." : "Could not delete that project.");
    }
  }

  async function removeAll() {
    setConfirmAll(false);
    setError(null);
    try {
      // The backend requires ?confirm=DELETE as a second, independent guard.
      const res = await fetch("/api/projects?confirm=DELETE", { method: "DELETE" });
      if (!res.ok) throw new Error();
      setProjects([]);
      refresh();
    } catch {
      setError(sw ? "Imeshindwa kufuta miradi yote." : "Could not delete all projects.");
    }
  }

  async function loadMore() {
    const cursor = projects.at(-1)?.id;
    if (!cursor || loadingMore || !moreProjects) return;
    setLoadingMore(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "100", before: cursor });
      const res = await fetch(`/api/projects?${params.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error();
      const next: Project[] = await res.json();
      setProjects((current) => [...current, ...next.filter((p) => !current.some((item) => item.id === p.id))]);
      setMoreProjects(next.length >= 100);
    } catch {
      setError(sw ? "Imeshindwa kupakia miradi zaidi." : "Could not load more projects.");
    } finally {
      setLoadingMore(false);
    }
  }

  if (!projects.length) {
    return (
      <div className="platform-panel flex min-h-52 flex-col items-center justify-center px-6 py-10 text-center">
        <div className="grid h-10 w-10 place-items-center rounded-lg border border-border bg-surface-2 text-accent">
          <span className="font-mono text-sm">W</span>
        </div>
        <h3 className="mt-4 text-sm font-semibold text-fg">{sw ? "Hakuna miradi bado" : "No projects yet"}</h3>
        <p className="mt-1 max-w-sm text-xs leading-5 text-fg-muted">
          {sw ? "Unda mradi ili kuweka pamoja mazungumzo na data." : "Create a project to keep its chats and datasets together."}
        </p>
      </div>
    );
  }

  return (
    <>
      {error && (
        <p className="mb-3 border-l-2 border-danger pl-3 text-[13px] text-danger">{error}</p>
      )}

      <ul className="platform-panel divide-y divide-border overflow-visible">
        {projects.map((p) => (
          <li key={p.id} className="relative">
            {renaming === p.id ? (
              <div className="bg-accent-soft p-4">
                <input
                  autoFocus
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void rename(p);
                    if (e.key === "Escape") setRenaming(null);
                  }}
                  className="w-full rounded-sm border border-border bg-bg px-2.5 py-1.5 text-[16px] outline-none focus:border-accent sm:text-[14px]"
                />
                <div className="mt-2 flex gap-2">
                  <button
                    onClick={() => void rename(p)}
                    className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3 py-1 text-[12px] text-accent-fg"
                  >
                    <IcoCheck size={12} />
                    {sw ? "Hifadhi" : "Save"}
                  </button>
                  <button
                    onClick={() => setRenaming(null)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-[12px] text-fg-muted"
                  >
                    <IcoClose size={12} />
                    {sw ? "Ghairi" : "Cancel"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="group relative">
                <Link
                  href={`/app/chat/${p.id}`}
                  className="flex min-h-[76px] items-center gap-3 px-3 py-3 pr-14 transition-colors duration-fast hover:bg-surface-2 sm:gap-4 sm:px-4"
                >
                  <span className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-md border border-border bg-surface-2 font-mono text-xs font-semibold text-accent">
                    {p.title.trim().slice(0, 1).toUpperCase() || "W"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                      <h2 className="min-w-0 truncate text-[13px] font-semibold text-fg">{p.title}</h2>
                      <span
                        className={`flex-shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide ${
                          p.mode === "researcher"
                            ? "border-warn/20 bg-warn-soft text-warn"
                            : "border-accent-line bg-accent-soft text-accent-strong"
                        }`}
                      >
                        {t(p.mode, language)}
                      </span>
                    </div>
                    {p.summary ? (
                      <p className="mt-1 truncate text-[11px] text-fg-muted">{p.summary}</p>
                    ) : (
                      <p className="mt-1 text-[11px] text-fg-faint">{sw ? "Mradi wa utafiti" : "Research workspace"}</p>
                    )}
                  </div>
                  <span className="hidden flex-shrink-0 font-mono text-[10px] text-fg-faint sm:block">
                    {new Date(p.created_at).toLocaleDateString(sw ? "sw-TZ" : "en-GB", { day: "2-digit", month: "short", year: "numeric" })}
                  </span>
                  <span aria-hidden="true" className="hidden text-fg-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent sm:block">↗</span>
                </Link>

                <button
                  onClick={(e) => {
                    e.preventDefault();
                    setMenuFor((cur) => (cur === p.id ? null : p.id));
                  }}
                  aria-label={sw ? "Chaguo za mradi" : "Project options"}
                  aria-expanded={menuFor === p.id}
                  className="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-md text-fg-faint transition-colors duration-fast hover:bg-surface-hover hover:text-fg"
                >
                  <IcoMore size={16} />
                </button>

                {menuFor === p.id && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setMenuFor(null)} />
                    <div className="animate-rise absolute right-2 top-11 z-50 w-44 overflow-hidden rounded-md border border-border bg-surface shadow-lg">
                      <button
                        onClick={() => {
                          setDraft(p.title);
                          setRenaming(p.id);
                          setMenuFor(null);
                        }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-fg transition-colors duration-fast hover:bg-surface-hover"
                      >
                        <IcoEdit size={13} className="text-fg-faint" />
                        {sw ? "Badilisha jina" : "Rename"}
                      </button>
                      <button
                        onClick={() => {
                          setConfirmOne(p);
                          setMenuFor(null);
                        }}
                        className="flex w-full items-center gap-2 border-t border-border px-3 py-2 text-left text-[13px] text-danger transition-colors duration-fast hover:bg-danger-soft"
                      >
                        <IcoTrash size={13} />
                        {sw ? "Futa mradi" : "Delete project"}
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>

      {moreProjects && (
        <div className="flex justify-center border-x border-b border-border bg-surface px-3 py-3">
          <button type="button" onClick={() => void loadMore()} disabled={loadingMore} className="platform-control text-xs disabled:opacity-60">
            {loadingMore
              ? sw ? "Inapakia…" : "Loading…"
              : sw ? "Pakia miradi zaidi" : "Load more projects"}
          </button>
        </div>
      )}

      <div className="mt-6 flex justify-end border-t border-border pt-4">
        <button
          onClick={() => setConfirmAll(true)}
          className="inline-flex items-center gap-1.5 text-[12px] uppercase tracking-widest text-fg-faint transition-colors duration-fast hover:text-danger"
        >
          <IcoTrash size={12} />
          {sw ? "Futa miradi yote" : "Delete all projects"}
        </button>
      </div>

      <ConfirmDialog
        open={confirmOne !== null}
        language={language}
        title={sw ? "Futa mradi huu?" : "Delete this project?"}
        body={
          sw
            ? `"${confirmOne?.title}" pamoja na gumzo, data, kumbukumbu na faili zote zilizotengenezwa zitafutwa kabisa. Kitendo hiki hakiwezi kutenduliwa.`
            : `"${confirmOne?.title}" and all its chats, datasets, memory and generated files will be permanently deleted. This cannot be undone.`
        }
        confirmLabel={sw ? "Futa mradi" : "Delete project"}
        onConfirm={() => confirmOne && void removeOne(confirmOne)}
        onCancel={() => setConfirmOne(null)}
      />

      <ConfirmDialog
        open={confirmAll}
        language={language}
        title={sw ? "Futa MIRADI YOTE?" : "Delete ALL projects?"}
        body={
          sw
            ? `Miradi yako ${projects.length} yote, pamoja na gumzo, data, kumbukumbu na faili zote, itafutwa kabisa. Hakuna njia ya kurudisha.`
            : `All ${projects.length} of your projects, including every chat, dataset, memory entry and generated file, will be permanently deleted. There is no way back.`
        }
        confirmLabel={sw ? "Futa yote" : "Delete everything"}
        requirePhrase="DELETE"
        onConfirm={() => void removeAll()}
        onCancel={() => setConfirmAll(false)}
      />
    </>
  );
}
