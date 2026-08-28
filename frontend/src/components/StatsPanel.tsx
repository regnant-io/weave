"use client";

import { useMemo } from "react";
import type { Language, UsageStats } from "@/lib/types";

/**
 * Usage analytics for the welcome screen.
 *
 * This replaces a pale "no projects yet" panel that told a returning user
 * nothing. It is deliberately about THEIR work — how much they've done, when
 * they work, what they reach for — rather than product metrics, and every
 * number comes from rows the app already writes.
 *
 * Design notes that matter at this density:
 *   * figures are set in the display serif and left-aligned, so a grid of eight
 *     tiles still reads as a page rather than as a dashboard widget;
 *   * every tile keeps its slot when its value is zero — a grid that reflows as
 *     data arrives feels broken;
 *   * the activity strip is twelve weeks of one-bit-per-day, which is enough to
 *     show a rhythm without implying precision the data doesn't have.
 */

const WEEKDAYS: Record<Language, string[]> = {
  en: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
  sw: ["Jumatatu", "Jumanne", "Jumatano", "Alhamisi", "Ijumaa", "Jumamosi", "Jumapili"],
};

function compact(n: number): string {
  if (!n) return "0";
  if (n >= 1_000_000) return `${Math.round(n / 100_000) / 10}M`;
  if (n >= 1000) return `${Math.round(n / 100) / 10}k`;
  return String(n);
}

/** "14:00–15:00" — an hour bucket, not a timestamp. */
function hourRange(h: number | null): string {
  if (h === null || h === undefined) return "—";
  const pad = (x: number) => String(((x % 24) + 24) % 24).padStart(2, "0");
  return `${pad(h)}:00–${pad(h + 1)}:00`;
}

function Tile({
  label,
  value,
  hint,
  wide,
}: {
  label: string;
  value: string;
  hint?: string;
  wide?: boolean;
}) {
  return (
    <div
      className={`min-w-0 border-t border-border pt-2.5 ${wide ? "col-span-2" : ""}`}
    >
      <div className="eyebrow truncate">{label}</div>
      <div className="mt-1 truncate font-display text-[26px] leading-none tracking-tight text-fg">
        {value}
      </div>
      {hint && <div className="mt-1 truncate text-[11.5px] text-fg-faint">{hint}</div>}
    </div>
  );
}

export default function StatsPanel({
  stats,
  language,
}: {
  stats: UsageStats | null;
  language: Language;
}) {
  const sw = language === "sw";

  // Grouped into weeks (columns) so the strip reads like a calendar, oldest left.
  const weeks = useMemo(() => {
    const days = stats?.activity ?? [];
    const out: Array<Array<{ date: string; active: boolean }>> = [];
    for (let i = 0; i < days.length; i += 7) out.push(days.slice(i, i + 7));
    return out;
  }, [stats]);

  if (!stats) {
    return (
      <aside className="border border-border bg-surface p-4">
        <div className="eyebrow mb-2">{sw ? "Takwimu" : "Your activity"}</div>
        <p className="text-[12.5px] leading-relaxed text-fg-faint">
          {sw
            ? "Takwimu hazipatikani kwa sasa."
            : "Activity stats aren't available right now."}
        </p>
      </aside>
    );
  }

  const streakHint =
    stats.current_streak > 0
      ? sw
        ? `bora zaidi ${stats.longest_streak}`
        : `best ${stats.longest_streak}`
      : sw
        ? `bora zaidi ${stats.longest_streak}`
        : `best ${stats.longest_streak}`;

  return (
    <aside className="border border-border bg-surface p-4 sm:p-5">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <div className="eyebrow">{sw ? "Takwimu zako" : "Your activity"}</div>
        {stats.last_active && (
          <div className="truncate text-[11px] text-fg-faint">
            {sw ? "mwisho" : "last"}{" "}
            {new Date(stats.last_active).toLocaleDateString(sw ? "sw-TZ" : "en-GB", {
              day: "numeric",
              month: "short",
            })}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Tile
          label={sw ? "Vipindi" : "Sessions"}
          value={compact(stats.sessions)}
          hint={`${compact(stats.projects)} ${sw ? "miradi" : "projects"}`}
        />
        <Tile
          label={sw ? "Ujumbe" : "Messages"}
          value={compact(stats.messages)}
          hint={`${compact(stats.prompts)} ${sw ? "maswali" : "prompts"}`}
        />
        <Tile label={sw ? "Tokeni" : "Total tokens"} value={compact(stats.total_tokens)} />
        <Tile
          label={sw ? "Siku hai" : "Active days"}
          value={compact(stats.active_days)}
        />
        <Tile
          label={sw ? "Mfululizo" : "Current streak"}
          value={`${stats.current_streak}`}
          hint={streakHint}
        />
        <Tile
          label={sw ? "Mrefu zaidi" : "Longest streak"}
          value={`${stats.longest_streak}`}
        />
        <Tile
          label={sw ? "Saa ya kilele" : "Peak hour"}
          value={hourRange(stats.peak_hour)}
          hint={
            stats.busiest_weekday !== null && stats.busiest_weekday !== undefined
              ? WEEKDAYS[sw ? "sw" : "en"][stats.busiest_weekday]
              : undefined
          }
          wide
        />
        <Tile
          label={sw ? "Modeli kipenzi" : "Favourite model"}
          value={stats.favourite_model || "—"}
          hint={
            stats.analyses
              ? `${compact(stats.analyses)} ${sw ? "uchambuzi" : "analyses"}`
              : undefined
          }
          wide
        />
      </div>

      {weeks.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <div className="eyebrow mb-2">{sw ? "Wiki 12 zilizopita" : "Last 12 weeks"}</div>
          <div className="flex gap-[3px] overflow-x-auto pb-1">
            {weeks.map((week, wi) => (
              <div key={wi} className="flex flex-shrink-0 flex-col gap-[3px]">
                {week.map((d) => (
                  <span
                    key={d.date}
                    title={d.date}
                    className={`block h-[9px] w-[9px] rounded-[1px] ${
                      d.active ? "bg-accent" : "bg-surface-3"
                    }`}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {stats.top_tools.length > 0 && (
        <div className="mt-3 border-t border-border pt-3">
          <div className="eyebrow mb-1.5">{sw ? "Zana zinazotumika" : "Most-used tools"}</div>
          <div className="flex flex-wrap gap-1.5">
            {stats.top_tools.map((tool) => (
              <span
                key={tool.name}
                className="inline-flex items-center gap-1.5 rounded-sm bg-surface-2 px-2 py-1 text-[11px] text-fg-muted"
              >
                {tool.name.replace(/_/g, " ")}
                <span className="font-mono text-[10px] text-fg-faint">{tool.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}
