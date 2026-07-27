"use client";

import { useState } from "react";
import type { Artifact, Citation, Dataset, Language, WebImage } from "@/lib/types";
import PanelFrame, { PanelEmpty } from "./PanelFrame";
import { ArtifactGrid, ArtifactView, FocusBar } from "./ArtifactViewer";
import {
  IcoChart,
  IcoCube,
  IcoDataset,
  IcoFile,
  IcoImage,
  IcoQuote,
} from "@/components/ui/icons";

/**
 * The six right-hand panels.
 *
 * Each is a distinct surface with its own layout, its own empty state and its
 * own width — deliberately NOT tabs sharing one shell. A chart grid, a PDF
 * reader, an image wall and a citation list want different affordances, and a
 * user comparing a chart against its sources wants both open at once.
 */

export type PanelId = "charts" | "visuals" | "docs" | "images" | "data" | "sources";

const VISUAL_TOOLS = new Set([
  "generate_3d",
  "create_simulation",
  "create_diagram",
  "create_animation",
  "render_custom",
]);

/** Which panel an artifact belongs to. */
export function categorise(a: Artifact): PanelId {
  if (VISUAL_TOOLS.has(a.tool ?? "")) return "visuals";
  if (a.mime === "model/gltf-binary") return "visuals";
  if (a.mime === "application/pdf") return "docs";
  if (a.mime === "text/html") return a.tool === "generate_deck" ? "docs" : "visuals";
  if (a.mime.startsWith("image/")) return "charts";
  if (a.mime === "text/csv" || a.mime === "application/json") return "data";
  return "docs";
}

export interface PanelData {
  artifacts: Artifact[];
  images: WebImage[];
  citations: Citation[];
  datasets: Dataset[];
}

export const PANEL_META: Record<
  PanelId,
  { icon: any; label: [sw: string, en: string]; width: number }
> = {
  charts: { icon: IcoChart, label: ["Chati", "Charts"], width: 440 },
  visuals: { icon: IcoCube, label: ["Taswira", "Visuals & 3D"], width: 560 },
  docs: { icon: IcoFile, label: ["Nyaraka", "Documents"], width: 520 },
  images: { icon: IcoImage, label: ["Picha", "Web images"], width: 380 },
  data: { icon: IcoDataset, label: ["Data", "Datasets"], width: 380 },
  sources: { icon: IcoQuote, label: ["Vyanzo", "Sources"], width: 360 },
};

export const PANEL_ORDER: PanelId[] = ["charts", "visuals", "docs", "images", "data", "sources"];

export function panelCounts(d: PanelData): Record<PanelId, number> {
  const c: Record<PanelId, number> = {
    charts: 0,
    visuals: 0,
    docs: 0,
    images: d.images.length,
    data: d.datasets.length,
    sources: d.citations.length,
  };
  for (const a of d.artifacts) {
    const p = categorise(a);
    if (p === "data") c.data += 1;
    else c[p] += 1;
  }
  return c;
}

/* -------------------------------------------------- artifact-backed panels */

function ArtifactPanelBody({
  id,
  data,
  language,
  focus,
  setFocus,
}: {
  id: PanelId;
  data: PanelData;
  language: Language;
  focus: Artifact | null;
  setFocus: (a: Artifact | null) => void;
}) {
  const items = data.artifacts.filter((a) => categorise(a) === id);
  const label = language === "sw" ? PANEL_META[id].label[0] : PANEL_META[id].label[1];

  if (focus) {
    return (
      <div className="animate-fade">
        <FocusBar a={focus} onBack={() => setFocus(null)} language={language} />
        <ArtifactView a={focus} language={language} />
      </div>
    );
  }
  return (
    <ArtifactGrid
      items={items}
      onOpen={setFocus}
      emptyText={
        language === "sw"
          ? `Hakuna ${label.toLowerCase()} bado. Zitaonekana hapa zikiundwa.`
          : `No ${label.toLowerCase()} yet. They appear here as they're created.`
      }
    />
  );
}

/* ------------------------------------------------------------ each surface */

export function Panel({
  id,
  data,
  language,
  onClose,
}: {
  id: PanelId;
  data: PanelData;
  language: Language;
  onClose: () => void;
}) {
  const [focus, setFocus] = useState<Artifact | null>(null);
  const meta = PANEL_META[id];
  const counts = panelCounts(data);
  const title = language === "sw" ? meta.label[0] : meta.label[1];

  return (
    <PanelFrame
      id={id}
      title={title}
      count={counts[id]}
      icon={meta.icon}
      onClose={onClose}
      defaultWidth={meta.width}
    >
      {id === "images" ? (
        <ImagesBody images={data.images} language={language} />
      ) : id === "sources" ? (
        <SourcesBody citations={data.citations} language={language} />
      ) : id === "data" ? (
        <DataBody
          datasets={data.datasets}
          artifacts={data.artifacts.filter((a) => categorise(a) === "data")}
          language={language}
          focus={focus}
          setFocus={setFocus}
        />
      ) : (
        <ArtifactPanelBody
          id={id}
          data={data}
          language={language}
          focus={focus}
          setFocus={setFocus}
        />
      )}
    </PanelFrame>
  );
}

function ImagesBody({ images, language }: { images: WebImage[]; language: Language }) {
  if (!images.length)
    return (
      <PanelEmpty
        text={language === "sw" ? "Hakuna picha za mtandaoni." : "No web images from this session."}
      />
    );
  return (
    <div className="grid grid-cols-2 gap-2">
      {images.map((im, i) => (
        <a
          key={im.url + i}
          href={im.url}
          target="_blank"
          rel="noreferrer"
          title={im.title || undefined}
          className="group animate-rise relative block aspect-square overflow-hidden border border-border bg-surface-2"
          style={{ animationDelay: `${Math.min(i, 8) * 28}ms` }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={im.url}
            alt={im.title || "web image"}
            loading="lazy"
            className="h-full w-full object-cover grayscale transition-all duration-500 ease-soft group-hover:scale-[1.04] group-hover:grayscale-0"
            onError={(e) => {
              (e.currentTarget.parentElement as HTMLElement).style.display = "none";
            }}
          />
        </a>
      ))}
    </div>
  );
}

function SourcesBody({ citations, language }: { citations: Citation[]; language: Language }) {
  if (!citations.length)
    return <PanelEmpty text={language === "sw" ? "Hakuna vyanzo bado." : "No sources cited yet."} />;
  return (
    <ol className="grid gap-1.5">
      {citations.map((c, i) => (
        <li key={i} className="animate-rise" style={{ animationDelay: `${Math.min(i, 8) * 24}ms` }}>
          <a
            href={c.url ?? "#"}
            target="_blank"
            rel="noreferrer"
            className="group flex gap-2 border-l-2 border-border py-1 pl-2.5 transition-colors duration-fast hover:border-accent"
          >
            <span className="font-mono text-[10px] text-fg-faint">
              {String(i + 1).padStart(2, "0")}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-xs leading-snug text-fg-muted group-hover:text-fg">
                {c.title || c.url}
              </span>
              <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                {c.source_type && <span className="eyebrow">{c.source_type}</span>}
                {c.access_status === "paywalled" && (
                  <span className="bg-warn-soft px-1 text-[10px] text-warn">
                    {language === "sw" ? "malipo" : "paywalled"}
                  </span>
                )}
                {c.predatory_flag && (
                  <span className="bg-danger-soft px-1 text-[10px] text-danger">
                    {language === "sw" ? "shaka" : "predatory"}
                  </span>
                )}
              </span>
            </span>
          </a>
        </li>
      ))}
    </ol>
  );
}

function DataBody({
  datasets,
  artifacts,
  language,
  focus,
  setFocus,
}: {
  datasets: Dataset[];
  artifacts: Artifact[];
  language: Language;
  focus: Artifact | null;
  setFocus: (a: Artifact | null) => void;
}) {
  if (focus) {
    return (
      <div className="animate-fade">
        <FocusBar a={focus} onBack={() => setFocus(null)} language={language} />
        <ArtifactView a={focus} language={language} />
      </div>
    );
  }
  if (!datasets.length && !artifacts.length)
    return <PanelEmpty text={language === "sw" ? "Hakuna data." : "No datasets in this project."} />;
  return (
    <div className="grid gap-2">
      {datasets.map((d) => (
        <div key={d.id} className="border border-border bg-surface p-2.5">
          <div className="truncate text-xs font-medium">{d.original_filename}</div>
          <div className="eyebrow mt-1">
            {d.row_count ?? "?"} {language === "sw" ? "safu" : "rows"} ·{" "}
            {d.column_profile?.column_count ?? "?"} {language === "sw" ? "nguzo" : "cols"} ·{" "}
            {d.status}
          </div>
        </div>
      ))}
      {artifacts.map((a, i) => (
        <button
          key={a.url + i}
          onClick={() => setFocus(a)}
          className="flex items-center gap-2 border border-border bg-surface px-2.5 py-2 text-left text-xs text-fg-muted transition-colors duration-fast hover:border-accent-line hover:text-fg"
        >
          <IcoDataset size={14} className="flex-shrink-0" />
          <span className="min-w-0 flex-1 truncate">{a.name}</span>
        </button>
      ))}
    </div>
  );
}
