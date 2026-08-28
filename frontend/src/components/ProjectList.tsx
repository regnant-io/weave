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

  if (!projects.length) {
    return (
      <div className="border border-dashed border-border-strong p-10 text-center text-fg-muted">
        {sw
          ? "Huna miradi bado. Anzisha mradi mpya kuanza."
          : "No projects yet. Create one to get started."}
      </div>
    );
  }

  return (
    <>
      {error && (
        <p className="mb-3 border-l-2 border-danger pl-3 text-[13px] text-danger">{error}</p>
      )}

      <ul className="grid gap-3 sm:grid-cols-2">
        {projects.map((p) => (
          <li key={p.id} className="relative">
            {renaming === p.id ? (
              <div className="border border-accent-line bg-surface p-4">
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
                  className="block border border-border bg-surface p-4 pr-11 transition-all duration-fast ease-soft hover:-translate-y-0.5 hover:border-border-strong hover:shadow-soft"
                >
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="min-w-0 truncate font-semibold">{p.title}</h2>
                    <span
                      className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
                        p.mode === "researcher"
                          ? "bg-warn/15 text-warn"
                          : "bg-accent-soft text-accent"
                      }`}
                    >
                      {t(p.mode, language)}
                    </span>
                  </div>
                  {p.summary && (
                    <p className="mt-2 line-clamp-2 text-sm text-fg-muted">{p.summary}</p>
                  )}
                  <div className="mt-3 text-xs text-accent">{t("chat", language)} →</div>
                </Link>

                <button
                  onClick={(e) => {
                    e.preventDefault();
                    setMenuFor((cur) => (cur === p.id ? null : p.id));
                  }}
                  aria-label={sw ? "Chaguo za mradi" : "Project options"}
                  aria-expanded={menuFor === p.id}
                  className="absolute right-2 top-3 grid h-8 w-8 place-items-center rounded-full text-fg-faint transition-colors duration-fast hover:bg-surface-hover hover:text-fg"
                >
                  <IcoMore size={16} />
                </button>

                {menuFor === p.id && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setMenuFor(null)} />
                    <div className="animate-rise absolute right-2 top-11 z-50 w-44 overflow-hidden rounded-sm border border-border bg-surface shadow-lg">
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
            : `All ${projects.length} of your projects — every chat, dataset, memory entry and generated file — will be permanently deleted. There is no way back.`
        }
        confirmLabel={sw ? "Futa yote" : "Delete everything"}
        requirePhrase="DELETE"
        onConfirm={() => void removeAll()}
        onCancel={() => setConfirmAll(false)}
      />
    </>
  );
}
