import type { Language } from "@/lib/types";

/**
 * Deterministic step titles, derived from tool + arguments.
 *
 * This is the instant half of the hybrid titling strategy: the chip must appear
 * with a meaningful label the moment work starts, with zero latency and zero
 * chance of being blank. If the model later supplies an authored title (a
 * `note` on the tool call), the backend sends it and it replaces this one in
 * place — but nothing ever waits on that.
 *
 * Bilingual, because the whole product is.
 */

type Pair = [sw: string, en: string];

function truncate(s: string, n = 52): string {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return truncate(url, 40);
  }
}

const VERBS: Record<string, Pair> = {
  web_search: ["Inatafuta mtandaoni", "Searching the web"],
  deep_research: ["Utafiti wa kina", "Researching"],
  search_library: ["Inatafuta maktaba", "Searching the library"],
  run_analysis: ["Inachambua data", "Running analysis"],
  query_warehouse: ["Inahoji ghala la data", "Querying the warehouse"],
  generate_visual: ["Inaunda chati", "Building a chart"],
  generate_deck: ["Inaunda wasilisho", "Building a deck"],
  generate_3d: ["Inaunda taswira ya 3D", "Building a 3D view"],
  create_diagram: ["Inachora mchoro", "Drawing a diagram"],
  create_simulation: ["Inaunda uigaji", "Building a simulation"],
  create_animation: ["Inaunda uhuishaji", "Animating an explainer"],
  check_citation: ["Inakagua rejea", "Checking a citation"],
  present_visual: ["Inaonyesha matokeo", "Presenting progress"],
  update_visual: ["Inasasisha taswira", "Updating the visual"],
  delete_visual: ["Inafuta taswira", "Removing a visual"],
  list_visuals: ["Inaorodhesha taswira", "Listing visuals"],
};

/** Title for a step that is starting, from the tool name and its arguments. */
export function titleForTool(tool: string, args: Record<string, any> = {}, lang: Language): string {
  const sw = lang === "sw";
  const pick = (p: Pair) => (sw ? p[0] : p[1]);
  const base = VERBS[tool] ? pick(VERBS[tool]) : tool.replace(/_/g, " ");

  switch (tool) {
    case "web_search":
    case "deep_research":
    case "search_library": {
      const q = args.query ? truncate(args.query) : "";
      if (!q) return base;
      return sw ? `${base}: “${q}”` : `${base} for “${q}”`;
    }
    case "run_analysis": {
      const code = String(args.code ?? "");
      const lines = code.trim() ? code.trim().split("\n").length : 0;
      if (!lines) return base;
      return sw ? `${base} (mistari ${lines})` : `${base} · ${lines} lines of Python`;
    }
    case "query_warehouse": {
      const sql = truncate(args.sql ?? "", 46);
      return sql ? `${base}: ${sql}` : base;
    }
    case "generate_visual": {
      const t = args?.spec?.title || args?.spec?.description;
      return t ? `${base}: ${truncate(t, 44)}` : base;
    }
    case "generate_deck": {
      const n = Array.isArray(args.slides) ? args.slides.length : 0;
      const t = args.title ? truncate(args.title, 36) : "";
      if (t && n) return sw ? `${base} “${t}” (slaidi ${n})` : `${base} “${t}” · ${n} slides`;
      return t ? `${base} “${t}”` : base;
    }
    case "generate_3d":
    case "create_diagram":
    case "create_simulation":
    case "create_animation": {
      const t = args.title || args?.spec?.title || args.topic;
      return t ? `${base}: ${truncate(t, 44)}` : base;
    }
    case "check_citation":
      return args.reference ? `${base}: ${truncate(args.reference, 44)}` : base;
    default: {
      const t = args.title || args.query || args.name;
      return t ? `${base}: ${truncate(String(t), 44)}` : base;
    }
  }
}

/** Collapsed one-line outcome for a finished step. */
export function summaryForResult(
  tool: string,
  result: Record<string, any> = {},
  lang: Language,
): string {
  const sw = lang === "sw";
  if (result.status && result.status !== "ok" && result.status !== "success") {
    return sw ? "imeshindwa" : String(result.status);
  }
  switch (tool) {
    case "web_search": {
      const n = result.results?.length ?? 0;
      return n ? (sw ? `matokeo ${n}` : `${n} results`) : "";
    }
    case "deep_research": {
      const p = result.pages_read ?? result.passages?.length ?? 0;
      return p ? (sw ? `kurasa ${p}` : `${p} pages`) : "";
    }
    case "search_library": {
      const n = result.results?.length ?? 0;
      return n ? (sw ? `vyanzo ${n}` : `${n} sources`) : "";
    }
    case "run_analysis": {
      const files = result.output_files?.length ?? 0;
      const ms = result.execution_time_ms;
      const bits: string[] = [];
      if (files) bits.push(sw ? `faili ${files}` : `${files} outputs`);
      if (ms) bits.push(`${Math.round(ms / 100) / 10}s`);
      return bits.join(" · ");
    }
    default: {
      const files = result.output_files?.length ?? 0;
      return files ? (sw ? `faili ${files}` : `${files} files`) : "";
    }
  }
}

/** Substep line for a page being read during research. */
export function readingLine(title: string, url: string, lang: Language): string {
  const label = title?.trim() ? truncate(title, 62) : host(url);
  return lang === "sw" ? `Inasoma ${label}` : `Read ${label}`;
}
