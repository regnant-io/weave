"use client";

import { memo, useEffect, useRef, useState } from "react";
import type { Artifact, Language } from "@/lib/types";
import {
  IcoCheck,
  IcoDownload,
  IcoExternal,
  IcoFile,
  IcoMaximize,
  IcoWarn,
} from "@/components/ui/icons";

/**
 * Generated output, rendered WHERE IT WAS PRODUCED.
 *
 * Previously every artifact was a pill you had to click to open a side panel.
 * That is the wrong default: a chart the assistant just drew IS the answer, not
 * a footnote to it, and making the reader leave the sentence to look at it
 * breaks the reading flow the whole layout exists to protect. The panel is still
 * there for full-size viewing and comparison — it is just no longer the only way
 * to see your own output.
 *
 * Two things keep this from being expensive on a long transcript:
 *
 *   * Interactive artifacts (HTML, 3D scenes, decks, PDFs) mount their iframe
 *     LAZILY, when scrolled near. A conversation with fifteen Babylon scenes
 *     would otherwise run fifteen WebGL contexts at once — browsers cap those,
 *     and the early ones get silently killed.
 *   * The component is memoised on the artifact URL, so a settled artifact never
 *     re-renders as text streams below it.
 */

type Kind = "image" | "page" | "pdf" | "data" | "archive" | "file";

function kindOf(a: Artifact): Kind {
  const mime = a.mime || "";
  if (mime.startsWith("image/")) return "image";
  if (mime === "text/html") return "page";
  if (mime === "application/pdf") return "pdf";
  if (mime === "text/csv" || mime === "application/json") return "data";
  if (mime === "application/gzip" || mime === "application/zip") return "archive";
  return "file";
}

/** Interactive surfaces get more room; a chart should not dominate the column. */
function frameHeight(a: Artifact): number {
  const tool = a.tool || "";
  if (tool === "create_3d_experience" || tool === "generate_3d") return 460;
  if (tool === "create_simulation") return 420;
  if (tool === "generate_deck") return 400;
  return 360;
}

/** Mount heavy embeds only once they are near the viewport. */
function useNearViewport<T extends HTMLElement>(rootMargin = "600px") {
  const ref = useRef<T | null>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // No IntersectionObserver (very old Safari): show it rather than never
    // showing it. Degrading to "always mounted" is the safe direction.
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setNear(true);
          io.disconnect();
        }
      },
      { rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [rootMargin]);

  return { ref, near };
}

/**
 * Whether this artifact was opened in a real browser before being shown.
 *
 * Only rendered when the answer is INTERESTING. A green tick on every single
 * output is decoration people stop reading within a day; what has to be
 * impossible to miss is the other case — an artifact released with known
 * defects after the repair budget ran out. The user is looking at something
 * that does not fully work, and they should learn that from the interface
 * rather than by clicking it.
 */
function VerifyBadge({ a, language }: { a: Artifact; language: Language }) {
  const sw = language === "sw";
  if (a.verified === undefined) return null;

  if (a.verified) {
    return (
      <span
        className="inline-flex shrink-0 items-center gap-1 text-ok"
        title={sw ? "Ilifunguliwa kwenye kivinjari halisi bila hitilafu"
                  : "Opened in a real browser; rendered without errors"}
      >
        <IcoCheck size={11} />
        <span className="text-2xs uppercase tracking-widest">
          {sw ? "Imehakikiwa" : "Verified"}
        </span>
      </span>
    );
  }

  const defects = a.defects ?? [];
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 text-warn"
      title={defects.join("\n") || (sw ? "Bado ina matatizo" : "Still has problems")}
    >
      <IcoWarn size={11} />
      <span className="text-2xs uppercase tracking-widest">
        {sw ? "Ina hitilafu" : "Has known faults"}
      </span>
    </span>
  );
}

function Chrome({
  a,
  language,
  onOpen,
  children,
}: {
  a: Artifact;
  language: Language;
  onOpen?: (a: Artifact) => void;
  children: React.ReactNode;
}) {
  const sw = language === "sw";
  return (
    <figure className="inline-artifact animate-rise my-3.5">
      <div className="inline-artifact-body">{children}</div>
      <figcaption className="inline-artifact-bar">
        <span className="min-w-0 flex-1 truncate">{a.name}</span>
        <VerifyBadge a={a} language={language} />
        {onOpen && (
          <button
            type="button"
            onClick={() => onOpen(a)}
            className="inline-artifact-act"
            aria-label={sw ? "Fungua kwa ukubwa kamili" : "Open full size"}
            title={sw ? "Fungua kwa ukubwa kamili" : "Open full size"}
          >
            <IcoMaximize size={12} />
          </button>
        )}
        <a
          href={a.url}
          target="_blank"
          rel="noreferrer"
          className="inline-artifact-act"
          aria-label={sw ? "Fungua kwenye kichupo kipya" : "Open in a new tab"}
          title={sw ? "Fungua kwenye kichupo kipya" : "Open in a new tab"}
        >
          <IcoExternal size={12} />
        </a>
        <a
          href={a.url}
          download={a.name}
          className="inline-artifact-act"
          aria-label={sw ? "Pakua" : "Download"}
          title={sw ? "Pakua" : "Download"}
        >
          <IcoDownload size={12} />
        </a>
      </figcaption>
    </figure>
  );
}

function InlineArtifactInner({
  artifact: a,
  language,
  onOpen,
}: {
  artifact: Artifact;
  language: Language;
  onOpen?: (a: Artifact) => void;
}) {
  const sw = language === "sw";
  const kind = kindOf(a);
  const [failed, setFailed] = useState(false);
  const { ref, near } = useNearViewport<HTMLDivElement>();

  if (kind === "image") {
    return (
      <Chrome a={a} language={language} onOpen={onOpen}>
        {failed ? (
          <div className="inline-artifact-fallback">
            {sw ? "Imeshindwa kupakia picha hii." : "This image could not be loaded."}
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={a.url}
            alt={a.name}
            loading="lazy"
            decoding="async"
            onError={() => setFailed(true)}
            onClick={() => onOpen?.(a)}
            className={`block max-h-[62vh] w-full bg-surface object-contain ${
              onOpen ? "cursor-zoom-in" : ""
            }`}
          />
        )}
      </Chrome>
    );
  }

  if (kind === "page" || kind === "pdf") {
    const height = frameHeight(a);
    return (
      <Chrome a={a} language={language} onOpen={onOpen}>
        <div ref={ref} style={{ height }} className="relative w-full bg-surface">
          {near ? (
            <iframe
              src={a.url}
              title={a.name}
              loading="lazy"
              /* Generated pages are self-contained and must not reach the parent
                 document or the network. allow-scripts WITHOUT allow-same-origin
                 puts the page in an opaque origin. */
              sandbox={kind === "pdf" ? undefined : "allow-scripts"}
              className="h-full w-full border-0 bg-white"
            />
          ) : a.preview ? (
            /* The screenshot taken while VERIFYING this page — a real picture of
               the real thing, so an unmounted embed still shows what it is
               instead of a line of grey text. It is also the only honest
               placeholder available: it is what the page actually rendered. */
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={a.preview}
              alt={a.name}
              loading="lazy"
              decoding="async"
              className="h-full w-full bg-white object-cover object-top opacity-90"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-fg-faint">
              {sw ? "Inasubiri kuonyeshwa…" : "Loads when scrolled into view"}
            </div>
          )}
        </div>
      </Chrome>
    );
  }

  // Data files and archives: a preview would be noise. Say what it is, offer it.
  return (
    <Chrome a={a} language={language} onOpen={kind === "data" ? onOpen : undefined}>
      <div className="flex items-center gap-3 bg-surface px-4 py-4">
        <IcoFile size={20} className="flex-shrink-0 text-fg-faint" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] text-fg">{a.name}</div>
          <div className="eyebrow mt-0.5">
            {a.mime}
            {a.bytes ? ` · ${formatBytes(a.bytes)}` : ""}
          </div>
        </div>
      </div>
    </Chrome>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 102.4) / 10} KB`;
  return `${Math.round(n / (1024 * 102.4)) / 10} MB`;
}

const InlineArtifact = memo(
  InlineArtifactInner,
  (a, b) =>
    a.artifact.url === b.artifact.url &&
    a.artifact.name === b.artifact.name &&
    a.language === b.language &&
    a.onOpen === b.onOpen,
);

export default InlineArtifact;
