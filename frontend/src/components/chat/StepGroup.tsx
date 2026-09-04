"use client";

import { memo, useEffect, useRef, useState } from "react";
import type { Artifact, Language } from "@/lib/types";
import type { StepBlock } from "@/lib/chatTypes";
import StepChip from "./StepChip";
import { IcoChevronRight, IcoWarn, iconForTool } from "@/components/ui/icons";

/**
 * A consecutive run of tool steps, shown as one phase of work.
 *
 * WHY GROUP AT ALL
 *
 * The transcript is a block timeline: the assistant narrates, works, narrates
 * again. That ordering is right and this does not change it — steps are grouped
 * only when they are ADJACENT, so prose between two steps still separates two
 * groups and the chronology is preserved exactly.
 *
 * What it changes is density. Twelve consecutive steps each drawing its own
 * left rail is twelve things on the page, and the reader has to scan all of
 * them to find the answer underneath. Collapsed, they are one line that says
 * what happened — and the individual record is still one click away, which is
 * what makes a long run auditable rather than merely quiet.
 *
 * WHEN IT DOES NOT COLLAPSE, WHICH IS THE PART THAT MATTERS
 *
 * Two cases stay open, because hiding them would be hiding the thing the reader
 * most needs:
 *
 *   * Anything still RUNNING. Watching the work is how a four-minute turn stays
 *     legible instead of reading as a hang.
 *   * Any step that FAILED. An error folded behind a chevron is an error nobody
 *     reads, and this product's worst failure mode is work that looks finished.
 *
 * And a short group does not collapse either. Hiding "searched the library,
 * ran the analysis" removes context the reader wanted; the density problem only
 * exists past about four steps, so that is where the behaviour changes.
 */

/** Below this many steps, collapsing removes more than it saves. */
const COLLAPSE_FROM = 4;

function toolIcons(steps: StepBlock[]) {
  const seen: string[] = [];
  for (const s of steps) {
    const key = s.tool || "step";
    if (!seen.includes(key)) seen.push(key);
  }
  return seen.slice(0, 5);
}

function StepGroupInner({
  steps,
  language,
  onOpenArtifact,
}: {
  steps: StepBlock[];
  language: Language;
  onOpenArtifact?: (a: Artifact) => void;
}) {
  const sw = language === "sw";
  const running = steps.some((s) => s.state === "running");
  const failed = steps.filter((s) => s.state === "error").length;
  const collapsible = steps.length >= COLLAPSE_FROM && !running && !failed;

  const [open, setOpen] = useState(!collapsible);
  const touched = useRef(false);

  // Fold up when the last step lands — but never against the user's own
  // choice, and never over an error.
  useEffect(() => {
    if (touched.current) return;
    setOpen(!collapsible);
  }, [collapsible]);

  if (steps.length === 1) {
    return (
      <StepChip step={steps[0]} language={language} onOpenArtifact={onOpenArtifact} />
    );
  }

  const total = steps.reduce(
    (ms, s) => ms + (s.endedAt ? s.endedAt - s.startedAt : 0),
    0,
  );
  const seconds = Math.round(total / 100) / 10;

  return (
    <div className="step-group my-2.5">
      {collapsible && (
        <button
          onClick={() => {
            touched.current = true;
            setOpen((v) => !v);
          }}
          aria-expanded={open}
          className="group flex w-full items-center gap-2 border-l-2 border-border py-1 pl-3 text-left transition-colors duration-300 ease-soft hover:border-accent-line"
        >
          <span className="flex flex-shrink-0 items-center -space-x-1">
            {toolIcons(steps).map((t, i) => {
              const Icon = iconForTool(t);
              return (
                <span
                  key={t + i}
                  className="grid h-[18px] w-[18px] place-items-center rounded-full border border-border bg-surface"
                >
                  <Icon size={10} className="text-fg-faint" />
                </span>
              );
            })}
          </span>
          <span className="min-w-0 flex-1 truncate text-[13px] text-fg-muted group-hover:text-fg">
            {sw ? `Hatua ${steps.length} za kazi` : `${steps.length} steps of work`}
          </span>
          {seconds >= 1 && (
            <span className="hidden flex-shrink-0 font-mono text-[10.5px] text-fg-faint sm:inline">
              {seconds}s
            </span>
          )}
          <IcoChevronRight
            size={13}
            className="chev flex-shrink-0 text-fg-faint"
            data-open={open}
          />
        </button>
      )}

      {/* Not `wv-collapse`: the group's children are themselves animating
          collapsibles, and nesting two grid-row animations makes both of them
          jitter. A group is opened deliberately, so it does not need one. */}
      {open && (
        <div className={collapsible ? "animate-fade" : undefined}>
          {failed > 0 && (
            <div className="mb-1 flex items-center gap-1.5 border-l-2 border-danger py-0.5 pl-3 text-[11.5px] text-danger">
              <IcoWarn size={12} className="flex-shrink-0" />
              {sw
                ? `Hatua ${failed} zilishindwa`
                : `${failed} step${failed === 1 ? "" : "s"} failed`}
            </div>
          )}
          {steps.map((s) => (
            <StepChip
              key={s.id}
              step={s}
              language={language}
              onOpenArtifact={onOpenArtifact}
            />
          ))}
        </div>
      )}
    </div>
  );
}

const StepGroup = memo(StepGroupInner);
export default StepGroup;
