// Shared visual language for every page the render service emits.
//
// Generated artifacts are viewed inside the Weave right-hand panel, so they must
// read as part of the product rather than as whatever a chart library defaults
// to. These tokens mirror frontend/src/app/globals.css: warm monochrome paper
// with a single burnt-orange ink, one grotesque plus a true monospace, sharp
// corners.
//
// Every page is fully self-contained — no CDN, no external font, no network —
// because artifacts are served from object storage under a strict sandbox.

export const TOKENS = {
  light: {
    bg: "#ffffff",
    bgSubtle: "#faf9f7",
    surface: "#ffffff",
    surface2: "#f4f3f0",
    border: "#e4e2dd",
    borderStrong: "#12110f",
    fg: "#12110f",
    fgMuted: "#57544e",
    fgFaint: "#8c887f",
    accent: "#d4451d",
    accentSoft: "rgba(212,69,29,.1)",
    grid: "#e4e2dd",
  },
  dark: {
    bg: "#0c0b0a",
    bgSubtle: "#121110",
    surface: "#151412",
    surface2: "#1d1b19",
    border: "#2a2724",
    borderStrong: "#f2f0eb",
    fg: "#f2f0eb",
    fgMuted: "#a8a399",
    fgFaint: "#6e6a62",
    accent: "#ff7043",
    accentSoft: "rgba(255,112,67,.14)",
    grid: "#2a2724",
  },
};

/**
 * Categorical series colours.
 *
 * The palette is deliberately shallow: orange leads, and the rest are warm and
 * cool neutrals that recede behind it. A rainbow would fight the design system
 * and imply meaning where there is none. Ordered for maximum separation at the
 * first four entries, which covers most real charts.
 */
export const SERIES = [
  "#d4451d",
  "#2f6b8a",
  "#7a8450",
  "#8a5a2f",
  "#5d5a8a",
  "#2f6b46",
  "#a8322f",
  "#6e6a62",
];

export const SERIES_DARK = [
  "#ff7043",
  "#63a4c9",
  "#b3c07a",
  "#d0995e",
  "#9a95d6",
  "#5fbe8a",
  "#ff6b6b",
  "#a8a399",
];

export function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Baseline CSS shared by every generated page. */
export function baseCss(theme = "light") {
  const t = TOKENS[theme === "dark" ? "dark" : "light"];
  return `
:root{
  --bg:${t.bg};--bg-subtle:${t.bgSubtle};--surface:${t.surface};--surface-2:${t.surface2};
  --border:${t.border};--border-strong:${t.borderStrong};--fg:${t.fg};--fg-muted:${t.fgMuted};
  --fg-faint:${t.fgFaint};--accent:${t.accent};--accent-soft:${t.accentSoft};--grid:${t.grid};
}
*{box-sizing:border-box}
/* Artifacts are viewed inside the Weave panel, so their type has to be the same
   voice as the app: one grotesque for everything, one monospace for labels and
   figures. These are system stacks rather than webfonts because an artifact has
   no network — it cannot fetch Geist or JetBrains Mono, and the nearest local
   equivalent is closer than a fallback to Georgia ever was. */
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg);
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;font-variant-numeric:lining-nums tabular-nums}
.wrap{padding:20px 22px;max-width:1100px;margin:0 auto}
.eyebrow{font-family:ui-monospace,"JetBrains Mono","SFMono-Regular",Menlo,Consolas,monospace;
  font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--fg-faint)}
h1.title{font-size:25px;font-weight:600;
  letter-spacing:-.022em;margin:.15em 0 .1em;line-height:1.15}
p.sub{color:var(--fg-muted);font-size:13.5px;line-height:1.6;margin:.5em 0 0;max-width:62ch}
.rule{height:1px;background:var(--border);margin:16px 0}
.rule-thick{height:2px;background:var(--border-strong);opacity:.85;margin:16px 0}
.caption{color:var(--fg-muted);font-size:12.5px;line-height:1.6;margin-top:10px}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}
.legend span{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:var(--fg-muted)}
.legend i{width:10px;height:10px;display:inline-block;border-radius:0}
button,select,input{font:inherit;color:inherit}
.btn{background:var(--surface);border:1px solid var(--border);padding:5px 11px;
  font-size:12px;cursor:pointer;transition:border-color .15s,color .15s}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation-duration:.01ms!important;transition-duration:.01ms!important}}
`;
}

/** Wrap body content in a complete, self-contained document. */
export function page({ title, subtitle, theme = "light", css = "", body = "", script = "", caption = "" }) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<style>${baseCss(theme)}${css}</style></head>
<body><div class="wrap">
${title ? `<div class="eyebrow">Weave</div><h1 class="title">${esc(title)}</h1>` : ""}
${subtitle ? `<p class="sub">${esc(subtitle)}</p>` : ""}
${title ? '<div class="rule"></div>' : ""}
${body}
${caption ? `<p class="caption">${esc(caption)}</p>` : ""}
</div>${script ? `<script>${script}</script>` : ""}</body></html>`;
}

export function palette(theme) {
  return theme === "dark" ? SERIES_DARK : SERIES;
}
