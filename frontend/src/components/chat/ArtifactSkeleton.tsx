"use client";

import type { Language } from "@/lib/types";
import type { PendingArtifact, PendingKind } from "@/lib/chatTypes";
import {
  IcoChart,
  IcoCube,
  IcoFile,
  IcoShapes,
  IcoSparkles,
  IcoTerminal,
  IcoWarn,
} from "@/components/ui/icons";

/**
 * Placeholder for an artifact that is still being produced.
 *
 * Rendering a deck, a simulation or a sandbox run takes seconds to minutes. If
 * nothing occupies that space the transcript just sits there and then jumps
 * when the result lands — which reads as a hang followed by a glitch. Reserving
 * shaped space says "a chart is being drawn" and keeps the layout stable, so
 * the arrival is a fill rather than a shove.
 *
 * The shape differs per kind on purpose: a skeleton that looks like the thing
 * you are waiting for sets the right expectation.
 */

const META: Record<
  PendingKind,
  { icon: any; label: [string, string]; aspect: string }
> = {
  chart: { icon: IcoChart, label: ["Inachora chati", "Drawing a chart"], aspect: "h-40" },
  document: { icon: IcoFile, label: ["Inaunda hati", "Building a document"], aspect: "h-32" },
  visual: { icon: IcoCube, label: ["Inaunda taswira", "Building a visual"], aspect: "h-44" },
  diagram: { icon: IcoShapes, label: ["Inachora mchoro", "Drawing a diagram"], aspect: "h-36" },
  simulation: {
    icon: IcoSparkles,
    label: ["Inaunda uigaji", "Building an interactive simulation"],
    aspect: "h-48",
  },
  animation: {
    icon: IcoSparkles,
    label: ["Inaunda uhuishaji", "Animating an explainer"],
    aspect: "h-40",
  },
  analysis: { icon: IcoTerminal, label: ["Inachambua data", "Running analysis"], aspect: "h-28" },
};

export default function ArtifactSkeleton({
  pending,
  language,
}: {
  pending: PendingArtifact;
  language: Language;
}) {
  const meta = META[pending.kind] ?? META.visual;
  const Icon = meta.icon;
  const label = language === "sw" ? meta.label[0] : meta.label[1];

  if (pending.failed) {
    return (
      <div className="animate-fade my-2 flex items-center gap-2 border border-dashed border-border px-3 py-2 text-xs text-fg-faint">
        <IcoWarn size={13} className="text-warn" />
        <span>
          {language === "sw"
            ? "Haikuweza kukamilisha taswira hii."
            : "This output could not be produced."}
        </span>
      </div>
    );
  }

  return (
    <div
      className={`animate-rise relative my-2.5 flex ${meta.aspect} w-full flex-col items-center justify-center overflow-hidden rounded-sm border border-border bg-surface-2/50`}
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      {/* A slow sweep across the whole placeholder — indeterminate on purpose.
          A percentage bar here would be a lie: nothing knows how long a model
          will take. */}
      <span className="skeleton-sweep pointer-events-none absolute inset-0" />

      <span className="relative z-[1] flex flex-col items-center gap-2">
        <Icon size={20} className="text-fg-faint" />
        <span className="shimmer text-[12.5px] font-medium">
          {pending.title ? `${label} · ${pending.title}` : label}
        </span>
      </span>

      <style>{`
        .skeleton-sweep {
          background: linear-gradient(
            100deg,
            transparent 20%,
            var(--accent-soft) 45%,
            transparent 70%
          );
          background-size: 220% 100%;
          animation: skelSweep 2.4s cubic-bezier(.4,.14,.3,1) infinite;
        }
        @keyframes skelSweep {
          0%   { background-position: 160% 0; }
          100% { background-position: -60% 0; }
        }
        @media (prefers-reduced-motion: reduce) { .skeleton-sweep { animation: none; } }
      `}</style>
    </div>
  );
}
