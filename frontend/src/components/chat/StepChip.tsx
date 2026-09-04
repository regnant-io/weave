"use client";

import { memo, useEffect, useRef, useState } from "react";
import type { Artifact } from "@/lib/types";
import type { StepBlock, Substep } from "@/lib/chatTypes";
import ArtifactSkeleton from "./ArtifactSkeleton";
import {
  IcoCheck,
  IcoChevronRight,
  IcoExternal,
  IcoWarn,
  iconForTool,
} from "@/components/ui/icons";

/**
 * One unit of agent work, inline in the transcript.
 *
 * Collapsed it is a single quiet line — a run that lasts hours stays readable
 * because finished work compacts to one row. Expanded it shows the substeps,
 * and each substep with a detail can expand again, so the whole run is
 * auditable after the fact without a separate log view.
 *
 * The open/close animation is `grid-template-rows: 0fr -> 1fr`, which animates
 * real auto height with no JS measurement. That matters here specifically: the
 * content is still GROWING while the step runs, and a scrollHeight-based
 * animation would fight every appended substep.
 */

function StepDot({ state }: { state: StepBlock["state"] }) {
  if (state === "running") {
    return (
      <span className="relative grid h-4 w-4 flex-shrink-0 place-items-center">
        <span className="pulse-dot absolute h-2 w-2 rounded-full bg-accent" />
        <span className="absolute h-4 w-4 rounded-full border border-accent-line" />
      </span>
    );
  }
  if (state === "error") {
    return <IcoWarn size={14} className="mt-px flex-shrink-0 text-danger" />;
  }
  if (state === "skipped") {
    return <span className="mt-1.5 h-1 w-2.5 flex-shrink-0 bg-fg-faint/50" />;
  }
  return <IcoCheck size={14} className="mt-px flex-shrink-0 text-ok" />;
}

function SubstepRow({ s }: { s: Substep }) {
  const [open, setOpen] = useState(false);
  const hasDetail = Boolean(s.detail);

  return (
    <li className="group/sub">
      <div className="flex items-start gap-2 py-[3px]">
        <span
          className={`mt-[7px] h-1 w-1 flex-shrink-0 rounded-full ${
            s.state === "running"
              ? "pulse-dot bg-accent"
              : s.state === "error"
                ? "bg-danger"
                : "bg-fg-faint/60"
          }`}
        />
        <div className="min-w-0 flex-1">
          {hasDetail ? (
            <button
              onClick={() => setOpen((v) => !v)}
              className="flex w-full items-start gap-1 text-left text-fg-muted transition-colors duration-fast hover:text-fg"
            >
              <IcoChevronRight
                size={11}
                className="chev mt-[5px] flex-shrink-0 opacity-50"
                data-open={open}
              />
              <span className="min-w-0 flex-1">{s.text}</span>
            </button>
          ) : s.url ? (
            <a
              href={s.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-baseline gap-1 text-fg-muted transition-colors duration-fast hover:text-accent"
            >
              <span className="min-w-0 break-words">{s.text}</span>
              <IcoExternal size={10} className="flex-shrink-0 opacity-50" />
            </a>
          ) : (
            <span className="text-fg-muted">{s.text}</span>
          )}

          {hasDetail && (
            <div className="wv-collapse" data-open={open}>
              <div className="wv-collapse-inner">
                <pre className="mt-1 max-h-64 overflow-auto border-l border-border bg-surface-2/60 px-2.5 py-1.5 font-mono text-[11px] leading-relaxed text-fg-muted">
                  {s.detail}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

function ArtifactPill({ a, onOpen }: { a: Artifact; onOpen?: (a: Artifact) => void }) {
  return (
    <button
      onClick={() => onOpen?.(a)}
      className="inline-flex max-w-full items-center gap-1.5 border border-border bg-surface px-2 py-1 text-[11px] text-fg-muted transition-all duration-fast ease-soft hover:border-accent-line hover:text-fg"
    >
      <span className="truncate">{a.name}</span>
    </button>
  );
}

function StepChipInner({
  step,
  onOpenArtifact,
  language,
}: {
  step: StepBlock;
  onOpenArtifact?: (a: Artifact) => void;
  language: "sw" | "en";
}) {
  const running = step.state === "running";
  // Auto-open while working so the user can watch; auto-close on completion so
  // a long run collapses into a clean, scannable record. A manual toggle wins
  // from then on — we never yank a panel the user deliberately opened.
  const [open, setOpen] = useState(running);
  const touched = useRef(false);
  const wasRunning = useRef(running);

  useEffect(() => {
    if (wasRunning.current && !running && !touched.current) setOpen(false);
    if (!wasRunning.current && running && !touched.current) setOpen(true);
    wasRunning.current = running;
  }, [running]);

  const ToolIcon = iconForTool(step.tool);
  const argEntries = Object.entries(step.args ?? {}).filter(
    ([k, v]) => k !== "code" && v !== undefined && v !== null && String(v) !== "",
  );
  // A step is worth opening if it can show ANYTHING. Previously this required
  // substeps, and only deep_research emits those — so almost every chip was an
  // inert row that expanded to nothing.
  const hasBody =
    step.substeps.length > 0 ||
    step.artifacts.length > 0 ||
    Boolean(step.error) ||
    Boolean(step.detail) ||
    argEntries.length > 0;
  const elapsed = step.endedAt ? Math.round((step.endedAt - step.startedAt) / 100) / 10 : null;

  return (
    <div className="animate-rise my-2.5">
      <div className="border-l-2 border-border pl-3 transition-colors duration-300 ease-soft hover:border-accent-line">
        <button
          onClick={() => {
            touched.current = true;
            setOpen((v) => !v);
          }}
          disabled={!hasBody}
          aria-expanded={open}
          className="group flex w-full items-center gap-2 py-0.5 text-left disabled:cursor-default"
        >
          <StepDot state={step.state} />
          <ToolIcon size={13} className="flex-shrink-0 text-fg-faint" />
          <span
            className={`min-w-0 flex-1 truncate text-[13px] ${
              running ? "shimmer font-medium" : "text-fg-muted group-hover:text-fg"
            }`}
          >
            {step.title}
          </span>
          {step.summary && !running && (
            <span className="hidden flex-shrink-0 font-mono text-[10.5px] text-fg-faint sm:inline">
              {step.summary}
            </span>
          )}
          {elapsed !== null && elapsed >= 1 && (
            <span className="hidden flex-shrink-0 font-mono text-[10.5px] text-fg-faint md:inline">
              {elapsed}s
            </span>
          )}
          {hasBody && (
            <IcoChevronRight
              size={13}
              className="chev flex-shrink-0 text-fg-faint"
              data-open={open}
            />
          )}
        </button>

        <div className="wv-collapse" data-open={open && hasBody}>
          <div className="wv-collapse-inner">
            <div className="pb-1.5 pt-1">
              {/* What happened when this step's artifact was opened in a real
                  browser. Placed above the arguments because it is the answer
                  to the question a reader actually has — did the thing work —
                  and because a verification that is only visible in a summary
                  chip is a claim without its evidence. */}
              {step.verification && (
                <div
                  className={`mb-1.5 border-l-2 pl-2 text-[11.5px] leading-snug ${
                    step.verification.state === "failed"
                      ? "border-danger text-danger"
                      : step.verification.state === "running"
                        ? "border-accent-line text-fg-muted"
                        : "border-ok text-fg-muted"
                  }`}
                >
                  <span className="eyebrow block">
                    {step.verification.state === "running"
                      ? "opening it in a browser…"
                      : step.verification.state === "failed"
                        ? `failed verification (attempt ${step.verification.attempt ?? 1})`
                        : "opened in a browser · rendered cleanly"}
                  </span>
                  {(step.verification.errors ?? []).map((e, i) => (
                    <div key={`e${i}`} className="mt-0.5">
                      {e}
                    </div>
                  ))}
                  {(step.verification.warnings ?? []).map((w, i) => (
                    <div key={`w${i}`} className="mt-0.5 text-warn">
                      {w}
                    </div>
                  ))}
                  {(step.verification.polish ?? []).map((n, i) => (
                    <div key={`p${i}`} className="mt-0.5 text-fg-muted">
                      · {n}
                    </div>
                  ))}
                </div>
              )}

              {argEntries.length > 0 && (
                <dl className="mb-1.5 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11.5px]">
                  {argEntries.map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="font-mono text-fg-faint">{k}</dt>
                      <dd className="min-w-0 truncate text-fg-muted">{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}

              {step.substeps.length > 0 && (
                <ul className="text-[12.5px] leading-relaxed">
                  {step.substeps.map((s) => (
                    <SubstepRow key={s.id} s={s} />
                  ))}
                </ul>
              )}

              {step.detail && (
                <pre className="mt-1.5 max-h-80 overflow-auto whitespace-pre-wrap break-words border-l border-border bg-surface-2/60 px-2.5 py-1.5 font-mono text-[11px] leading-relaxed text-fg-muted">
                  {step.detail}
                </pre>
              )}

              {step.error && (
                <div className="mt-1.5 border-l-2 border-danger bg-danger-soft px-2.5 py-1.5 font-mono text-[11px] text-danger">
                  {step.error}
                </div>
              )}

              {step.artifacts.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <span className="eyebrow self-center">
                    {language === "sw" ? "Matokeo" : "Output"}
                  </span>
                  {step.artifacts.map((a, i) => (
                    <ArtifactPill key={i} a={a} onOpen={onOpenArtifact} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Announced-but-not-yet-produced output sits OUTSIDE the collapsible, so
          the user sees it even when the step is collapsed — the whole point is
          that a long render is visible while it happens. */}
      {step.pending
        .filter((p) => !p.resolved)
        .map((p) => (
          <ArtifactSkeleton key={p.id} pending={p} language={language} />
        ))}
    </div>
  );
}

/* A settled step never needs to re-render again — that is what keeps an
   hours-long transcript cheap. */
const StepChip = memo(StepChipInner, (a, b) => {
  const x = a.step;
  const y = b.step;
  return (
    x.id === y.id &&
    x.title === y.title &&
    x.state === y.state &&
    x.summary === y.summary &&
    x.verification?.state === y.verification?.state &&
    x.error === y.error &&
    x.detail === y.detail &&
    x.endedAt === y.endedAt &&
    x.substeps.length === y.substeps.length &&
    x.artifacts.length === y.artifacts.length &&
    x.pending.length === y.pending.length &&
    x.pending.every((p, i) => p.resolved === y.pending[i]?.resolved) &&
    // last substep can mutate in place (running -> done)
    x.substeps[x.substeps.length - 1]?.state === y.substeps[y.substeps.length - 1]?.state &&
    a.onOpenArtifact === b.onOpenArtifact
  );
});

export default StepChip;
