"use client";

import { useState } from "react";
import type { Artifact, Language } from "@/lib/types";
import { IcoDownload, IcoExternal, IcoFile } from "@/components/ui/icons";

/** Renders one artifact at full size inside whichever panel opened it. */
export function ArtifactView({ a, language }: { a: Artifact; language: Language }) {
  const [failed, setFailed] = useState(false);

  if (a.mime.startsWith("image/")) {
    // No texture behind artefacts: a noise/grid overlay competes with a chart's
    // own gridlines and makes a transparent PNG look dirty. Plain surface.
    return (
      <div className="relative border border-border bg-surface-2 p-2">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={a.url}
          alt={a.name}
          className="mx-auto max-h-[70vh] w-auto max-w-full"
          onError={() => setFailed(true)}
        />
        {failed && (
          <p className="p-6 text-center text-sm text-fg-muted">
            {language === "sw" ? "Imeshindwa kupakia." : "Could not load this image."}
          </p>
        )}
      </div>
    );
  }

  if (a.mime === "text/html") {
    return (
      <iframe
        src={a.url}
        title={a.name}
        /* Generated pages are self-contained and must not reach the parent
           document or the network. allow-scripts WITHOUT allow-same-origin puts
           the page in an opaque origin. */
        sandbox="allow-scripts"
        loading="lazy"
        className="h-[72vh] w-full border border-border bg-white"
      />
    );
  }

  if (a.mime === "application/pdf") {
    return (
      <iframe
        src={a.url}
        title={a.name}
        loading="lazy"
        className="h-[74vh] w-full border border-border bg-white"
      />
    );
  }

  return (
    <div className="border border-border bg-surface-2 p-6 text-center">
      <IcoFile size={22} className="mx-auto mb-2 text-fg-faint" />
      <p className="mb-3 text-sm text-fg-muted">{a.name}</p>
      <a
        href={a.url}
        download
        className="inline-flex items-center gap-1.5 border border-border-strong px-3 py-1.5 text-xs uppercase tracking-widest transition-colors duration-fast hover:bg-fg hover:text-bg"
      >
        <IcoDownload size={13} />
        {language === "sw" ? "Pakua" : "Download"}
      </a>
    </div>
  );
}

/** Back-bar shown above a focused artifact. */
export function FocusBar({
  a,
  onBack,
  language,
}: {
  a: Artifact;
  onBack: () => void;
  language: Language;
}) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <button onClick={onBack} className="eyebrow transition-colors duration-fast hover:text-fg">
        ← {language === "sw" ? "Rudi" : "Back"}
      </button>
      <span className="ml-auto truncate font-mono text-[11px] text-fg-faint">{a.name}</span>
      <a
        href={a.url}
        target="_blank"
        rel="noreferrer"
        aria-label="Open in new tab"
        className="text-fg-faint transition-colors duration-fast hover:text-accent"
      >
        <IcoExternal size={13} />
      </a>
    </div>
  );
}

/** Grid of artifact cards, used by the charts/visuals/documents panels. */
export function ArtifactGrid({
  items,
  onOpen,
  emptyText,
}: {
  items: Artifact[];
  onOpen: (a: Artifact) => void;
  emptyText: string;
}) {
  if (!items.length) {
    return (
      <div className="flex h-40 items-center justify-center border border-dashed border-border">
        <p className="px-6 text-center text-xs leading-relaxed text-fg-faint">{emptyText}</p>
      </div>
    );
  }
  return (
    <div className="grid gap-2">
      {items.map((a, i) => (
        <button
          key={a.url + i}
          onClick={() => onOpen(a)}
          className="group animate-rise block border border-border bg-surface text-left transition-all duration-fast ease-soft hover:border-accent-line"
          style={{ animationDelay: `${Math.min(i, 8) * 28}ms` }}
        >
          {a.mime.startsWith("image/") ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={a.url}
              alt={a.name}
              loading="lazy"
              className="max-h-52 w-full bg-surface-2 object-contain p-1.5"
            />
          ) : (
            <div className="flex h-24 items-center justify-center bg-surface-2">
              <IcoFile size={20} className="text-fg-faint" />
            </div>
          )}
          <div className="flex items-center gap-2 border-t border-border px-2.5 py-1.5">
            <span className="min-w-0 flex-1 truncate text-xs text-fg-muted group-hover:text-fg">
              {a.name}
            </span>
            {a.tool && <span className="eyebrow flex-shrink-0">{a.tool.replace(/_/g, " ")}</span>}
          </div>
        </button>
      ))}
    </div>
  );
}
