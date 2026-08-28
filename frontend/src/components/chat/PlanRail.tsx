"use client";

import { useEffect, useMemo, useState } from "react";
import type { Language, Plan, PlanStep } from "@/lib/types";
import { IcoChevronRight } from "@/components/ui/icons";

/**
 * The plan the assistant committed to, and where it has got to.
 *
 * WHY THIS IS AT THE TOP OF THE TURN AND NOT IN A SIDE PANEL
 * ----------------------------------------------------------
 * On a run that takes minutes, the honest question in the reader's head is "is
 * this going anywhere, and how much longer?". Step chips answer the first but
 * not the second: they tell you what is happening now with no denominator. A
 * ledger with a total is the only thing that makes a long run feel bounded
 * rather than open-ended, and that has to be where the eye already is.
 *
 * It collapses to a single line once the work is done, because at that point
 * the answer is the thing worth reading and the plan is provenance.
 */

const LABELS = {
  en: {
    plan: "Plan",
    of: (a: number, b: number) => `${a} of ${b} done`,
    complete: "all steps complete",
    checks: "Checks",
    working: "working",
  },
  sw: {
    plan: "Mpango",
    of: (a: number, b: number) => `${a} kati ya ${b} zimekamilika`,
    complete: "hatua zote zimekamilika",
    checks: "Ukaguzi",
    working: "inaendelea",
  },
} as const;

function StatusMark({ status }: { status: PlanStep["status"] }) {
  // Deliberately geometric rather than iconographic. At this size an icon set
  // reads as clutter down the left edge of six rows; a square that fills is
  // legible at a glance and carries the state on its own.
  const base = "mt-[7px] h-[7px] w-[7px] shrink-0 transition-all duration-300 ease-soft";
  if (status === "done") return <span className={`${base} bg-fg`} aria-hidden />;
  if (status === "failed")
    return <span className={`${base} bg-danger`} aria-hidden />;
  if (status === "skipped")
    return <span className={`${base} border border-border-mid`} aria-hidden />;
  if (status === "active")
    return (
      <span className={`${base} animate-pulse bg-accent ring-2 ring-accent-soft`} aria-hidden />
    );
  return <span className={`${base} border border-border-mid`} aria-hidden />;
}

export default function PlanRail({
  plan,
  language,
  live = false,
}: {
  plan: Plan;
  language: Language;
  /** True while the turn is still running — keeps the rail open. */
  live?: boolean;
}) {
  const t = LABELS[language] ?? LABELS.en;
  const steps = plan.steps ?? [];
  const done = steps.filter(
    (s) => s.status === "done" || s.status === "skipped",
  ).length;
  const finished = steps.length > 0 && done === steps.length;

  // Open while the work is live; settle closed once it is over. `userSet`
  // stops that automatic collapse from yanking the panel shut under a reader
  // who deliberately opened it.
  const [open, setOpen] = useState(live);
  const [userSet, setUserSet] = useState(false);
  useEffect(() => {
    if (!userSet) setOpen(live);
  }, [live, userSet]);

  const pct = steps.length ? Math.round((done / steps.length) * 100) : 0;
  const activeTitle = useMemo(
    () => steps.find((s) => s.status === "active")?.title ?? "",
    [steps],
  );

  if (!steps.length) return null;

  return (
    <section
      className="my-3 border border-border bg-surface-2/60"
      aria-label={t.plan}
    >
      <button
        type="button"
        onClick={() => {
          setUserSet(true);
          setOpen((v) => !v);
        }}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors duration-fast hover:bg-surface-hover/50"
        aria-expanded={open}
      >
        <IcoChevronRight
          size={12}
          className={`shrink-0 text-fg-faint transition-transform duration-fast ${
            open ? "rotate-90" : ""
          }`}
        />
        <span className="text-2xs uppercase tracking-widest text-fg-faint">{t.plan}</span>

        {/* The denominator. This is the whole point of the component. */}
        <span className="ml-auto shrink-0 font-mono text-2xs tabular-nums text-fg-muted">
          {finished ? t.complete : t.of(done, steps.length)}
        </span>
      </button>

      {/* A hairline that fills. Enough to read progress peripherally without
          adding a second number to the header. */}
      <div className="h-px w-full bg-border" aria-hidden>
        <div
          className="h-px bg-accent transition-all duration-slow ease-expo"
          style={{ width: `${pct}%` }}
        />
      </div>

      {!open && !finished && activeTitle && (
        <p className="truncate px-3 py-1.5 text-xs text-fg-muted">{activeTitle}</p>
      )}

      {open && (
        <div className="px-3 pb-3 pt-2.5">
          {plan.goal && (
            <p className="mb-2.5 border-l-2 border-accent-line pl-2.5 text-[13px] leading-snug text-fg-muted">
              {plan.goal}
            </p>
          )}
          <ol className="space-y-1.5">
            {steps.map((s) => (
              <li key={s.n} className="flex items-start gap-2.5">
                <StatusMark status={s.status} />
                <span
                  className={`text-[13px] leading-snug ${
                    s.status === "done" || s.status === "skipped"
                      ? "text-fg-faint"
                      : s.status === "failed"
                        ? "text-danger"
                        : "text-fg"
                  }`}
                >
                  {s.title}
                  {s.note && (
                    <span className="ml-1.5 text-fg-faint">— {s.note}</span>
                  )}
                </span>
              </li>
            ))}
          </ol>

          {plan.checks && plan.checks.length > 0 && (
            <div className="mt-3 border-t border-border pt-2">
              <p className="mb-1 text-2xs uppercase tracking-widest text-fg-faint">
                {t.checks}
              </p>
              <ul className="space-y-0.5">
                {plan.checks.map((c, i) => (
                  <li key={i} className="text-xs leading-snug text-fg-muted">
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
