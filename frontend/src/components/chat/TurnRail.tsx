"use client";

import { memo } from "react";
import type { Language } from "@/lib/types";

/**
 * Right-edge navigation rail.
 *
 * One tick per turn — long dash for a prompt, short for a response — so a
 * transcript with fifty exchanges can be navigated by shape rather than by
 * scrolling. The active tick is the turn currently in view.
 */
function TurnRailInner({
  turns,
  activeId,
  onJump,
  language,
}: {
  turns: { id: string; role: "user" | "assistant"; label: string }[];
  activeId: string | null;
  onJump: (id: string) => void;
  language: Language;
}) {
  if (turns.length < 2) return null;

  return (
    <nav
      aria-label={language === "sw" ? "Sogeza kwenye mazungumzo" : "Jump to a turn"}
      className="pointer-events-none absolute right-1 top-1/2 z-20 hidden -translate-y-1/2 md:block"
    >
      <ul className="pointer-events-auto flex max-h-[60vh] flex-col items-end gap-[5px] overflow-hidden py-2">
        {turns.map((t) => {
          const active = t.id === activeId;
          const isUser = t.role === "user";
          return (
            <li key={t.id} className="group/tick relative flex items-center">
              {/* Label reveals on hover — no permanent visual weight. */}
              <span className="pointer-events-none absolute right-full mr-2 max-w-[15rem] translate-x-1 truncate whitespace-nowrap border border-border bg-surface px-2 py-1 text-[11px] text-fg-muted opacity-0 shadow-soft transition-all duration-fast ease-soft group-hover/tick:translate-x-0 group-hover/tick:opacity-100">
                {t.label}
              </span>
              <button
                onClick={() => onJump(t.id)}
                aria-label={t.label}
                aria-current={active ? "true" : undefined}
                className={`block h-[3px] rounded-full transition-all duration-300 ease-expo ${
                  isUser ? "w-4" : "w-2.5"
                } ${
                  active
                    ? "bg-accent"
                    : "bg-border-mid group-hover/tick:bg-fg-faint"
                }`}
              />
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export default memo(TurnRailInner);
