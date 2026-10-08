"use client";

import { useMemo } from "react";
import type { Language, UsageStats } from "@/lib/types";

const WEEKDAYS: Record<Language, string[]> = {
  en: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
  sw: ["Jumatatu", "Jumanne", "Jumatano", "Alhamisi", "Ijumaa", "Jumamosi", "Jumapili"],
};

function compact(n: number): string {
  if (n >= 1_000_000) return `${Math.round(n / 100_000) / 10}M`;
  if (n >= 1000) return `${Math.round(n / 100) / 10}k`;
  return String(n);
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="min-w-0 px-4 py-3 sm:px-5">
      <div className="truncate text-[11px] font-medium text-fg-faint">{label}</div>
      <div className="mt-1.5 truncate font-mono text-[22px] font-semibold leading-none tracking-tight text-fg">
        {value}
      </div>
      {note && <div className="mt-1 truncate text-[10px] text-fg-faint">{note}</div>}
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
  const weeks = useMemo(() => {
    const days = stats?.activity ?? [];
    const out: Array<Array<{ date: string; active: boolean }>> = [];
    for (let i = 0; i < days.length; i += 7) out.push(days.slice(i, i + 7));
    return out;
  }, [stats]);

  if (!stats) {
    return (
      <section className="platform-panel flex min-h-20 items-center px-4 py-3 text-[13px] text-fg-muted">
        {sw ? "Takwimu za matumizi hazipatikani kwa sasa." : "Usage data is temporarily unavailable."}
      </section>
    );
  }

  const weekday = stats.busiest_weekday == null ? null : WEEKDAYS[language][stats.busiest_weekday];
  const peakHour = stats.peak_hour == null
    ? null
    : `${String(stats.peak_hour).padStart(2, "0")}:00`;

  return (
    <section className="platform-panel overflow-hidden" aria-label={sw ? "Muhtasari wa matumizi" : "Usage overview"}>
      <div className="grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-4 sm:divide-y-0">
        <Metric label={sw ? "Miradi" : "Projects"} value={compact(stats.projects)} />
        <Metric label={sw ? "Ujumbe" : "Messages"} value={compact(stats.messages)} note={`${compact(stats.prompts)} ${sw ? "maulizo" : "prompts"}`} />
        <Metric label={sw ? "Seti za data" : "Datasets"} value={compact(stats.datasets)} />
        <Metric label={sw ? "Siku za kazi" : "Active days"} value={compact(stats.active_days)} />
      </div>

      <div className="grid gap-5 border-t border-border px-4 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-5">
        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between gap-3">
            <h2 className="text-xs font-semibold text-fg">{sw ? "Shughuli za wiki 12" : "Activity over 12 weeks"}</h2>
            <span className="font-mono text-[10px] text-fg-faint">{stats.activity.filter((d) => d.active).length} / 84</span>
          </div>
          <div
            className="grid w-fit grid-flow-col grid-rows-7 gap-[3px]"
            role="img"
            aria-label={sw ? "Shughuli za siku kwa siku katika wiki 12 zilizopita" : "Daily activity over the last 12 weeks"}
          >
            {weeks.flatMap((week) => week).map((day) => (
              <span
                key={day.date}
                title={`${day.date}${day.active ? sw ? " · shughuli" : " · activity" : ""}`}
                className={`h-[10px] w-[10px] rounded-[2px] ${day.active ? "bg-accent" : "bg-surface-3"}`}
              />
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-7 gap-y-3 border-t border-border pt-3 sm:grid-cols-1 sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0">
          <div>
            <div className="text-[10px] font-medium text-fg-faint">{sw ? "Mfululizo wa sasa" : "Current streak"}</div>
            <div className="mt-0.5 font-mono text-sm font-semibold">{stats.current_streak} <span className="font-sans text-[11px] font-normal text-fg-faint">{sw ? "siku" : "days"}</span></div>
          </div>
          <div>
            <div className="text-[10px] font-medium text-fg-faint">{sw ? "Saa yenye shughuli nyingi" : "Peak activity"}</div>
            <div className="mt-0.5 truncate text-xs font-medium">{peakHour ?? "None"}{weekday ? ` · ${weekday}` : ""}</div>
          </div>
        </div>
      </div>

      {stats.top_tools.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3 sm:px-5">
          <span className="mr-1 text-[10px] font-medium text-fg-faint">{sw ? "Zana zinazotumika" : "Recent tools"}</span>
          {stats.top_tools.map((tool) => (
            <span key={tool.name} className="inline-flex items-center gap-1.5 rounded border border-border bg-surface-2 px-2 py-1 text-[10px] text-fg-muted">
              {tool.name.replace(/_/g, " ")}
              <span className="font-mono text-fg-faint">{tool.count}</span>
            </span>
          ))}
          <span className="ml-auto truncate text-[10px] text-fg-faint">
            {sw ? "Modeli" : "Model"}: {stats.favourite_model || "None"}
          </span>
        </div>
      )}
    </section>
  );
}
