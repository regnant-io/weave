// Chart styling, applied to EVERY chart before it renders.
//
// The reason this exists server-side rather than as advice in a prompt: a model
// asked to "make it look nice" will produce a different-looking chart every
// time, and a set of charts that each look fine individually but share no visual
// language reads as amateur. Vega-Lite's defaults (blue, 5pt Arial-ish labels,
// full box border, gridlines as dark as the data) are also simply not good.
//
// So the caller supplies DATA and ENCODING; this file supplies the design. The
// spec's own `config` still wins if it sets something explicitly, so a model
// that genuinely needs a different treatment can still have one.
//
// The choices here mirror frontend/src/app/globals.css and lib/theme.js:
//   * warm monochrome ink, one burnt-orange accent
//   * gridlines recede (they are scaffolding, not data)
//   * no chart border, no chart title box — the surrounding page provides those
//   * tabular figures on axes so numbers don't jitter between frames
//   * generous label padding; cramped labels are the main "generated" tell

import { TOKENS, SERIES, SERIES_DARK } from "./theme.js";

const FONT =
  'ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif';
const MONO = 'ui-monospace,SFMono-Regular,Consolas,monospace';

export function vegaConfig(theme = "light") {
  const dark = theme === "dark";
  const t = TOKENS[dark ? "dark" : "light"];
  const series = dark ? SERIES_DARK : SERIES;

  return {
    background: "transparent",
    font: FONT,
    padding: { left: 8, top: 12, right: 16, bottom: 8 },

    title: {
      // Chart titles use the same face as everything else now — the display
      // serif they used to be set in is gone from the whole product.
      font: FONT,
      fontSize: 15,
      fontWeight: 600,
      color: t.fg,
      anchor: "start",
      offset: 14,
      subtitleFont: FONT,
      subtitleFontSize: 11.5,
      subtitleColor: t.fgMuted,
      subtitlePadding: 6,
    },

    axis: {
      labelFont: FONT,
      labelFontSize: 11,
      labelColor: t.fgMuted,
      labelPadding: 6,
      labelOverlap: "greedy",
      titleFont: MONO,
      titleFontSize: 9.5,
      titleFontWeight: 500,
      titleColor: t.fgFaint,
      titlePadding: 10,
      // Uppercase mono axis titles read as labels rather than as more data.
      titleAngle: 0,
      domainColor: t.border,
      domainWidth: 1,
      tickColor: t.border,
      tickSize: 4,
      tickOpacity: 0.6,
      grid: true,
      gridColor: t.grid,
      gridOpacity: dark ? 0.5 : 0.75,
      gridWidth: 1,
      gridDash: [],
    },
    // A vertical bar/line chart does not need vertical gridlines; they only add
    // noise behind the marks.
    axisX: { grid: false, titleAlign: "left", titleAnchor: "start" },
    axisY: { domain: false, ticks: false, titleAlign: "left", titleAnchor: "end" },

    legend: {
      labelFont: FONT,
      labelFontSize: 11,
      labelColor: t.fgMuted,
      titleFont: MONO,
      titleFontSize: 9.5,
      titleColor: t.fgFaint,
      symbolType: "square",
      symbolSize: 90,
      symbolStrokeWidth: 0,
      orient: "top",
      direction: "horizontal",
      offset: 8,
      padding: 0,
      rowPadding: 4,
      columnPadding: 14,
    },

    view: { stroke: null, continuousWidth: 520, continuousHeight: 300 },

    range: {
      category: series,
      // Sequential ramps run from paper to full accent so a heatmap belongs to
      // the same system as a bar chart.
      heatmap: dark
        ? ["#1d1b19", "#4a2a1c", "#8a3f22", "#c75a2c", "#ff7043"]
        : ["#faf5f2", "#f3d9cd", "#e8a488", "#dd7047", "#d4451d"],
      ramp: dark
        ? ["#26241f", "#6b3a22", "#b5522a", "#ff7043"]
        : ["#f6ece7", "#eab8a1", "#dd7047", "#a8320f"],
      diverging: dark
        ? ["#63a4c9", "#9dc3d8", "#3d3934", "#ff9b7a", "#ff7043"]
        : ["#2f6b8a", "#8fb3c4", "#e4e2dd", "#e9a184", "#d4451d"],
    },

    mark: { color: series[0], tooltip: true },
    bar: { color: series[0], cornerRadius: 0, binSpacing: 2 },
    line: { color: series[0], strokeWidth: 2, strokeCap: "round", strokeJoin: "round" },
    area: { color: series[0], opacity: 0.16, line: { strokeWidth: 2 } },
    point: { color: series[0], size: 55, filled: true, opacity: 0.85 },
    circle: { color: series[0], size: 55, opacity: 0.8 },
    rect: { color: series[0] },
    rule: { color: t.fgFaint, strokeWidth: 1 },
    text: { font: FONT, fontSize: 11, color: t.fgMuted },

    header: {
      labelFont: MONO,
      labelFontSize: 10,
      labelColor: t.fgFaint,
      titleFont: MONO,
      titleFontSize: 10,
      titleColor: t.fgFaint,
    },
  };
}

/**
 * Merge the house style into a caller's spec.
 *
 * The spec's own `config` is applied ON TOP, so an explicit choice by the model
 * still wins — this sets the floor, it does not take the decision away.
 */
export function applyTheme(spec, theme = "light") {
  if (!spec || typeof spec !== "object") return spec;
  const base = vegaConfig(theme);
  const out = { ...spec, config: { ...base, ...(spec.config || {}) } };

  // Deep-merge the nested config groups the caller may have touched, or a spec
  // that sets `config.axis.title` would otherwise wipe the whole axis theme.
  for (const key of Object.keys(spec.config || {})) {
    if (base[key] && typeof base[key] === "object" && !Array.isArray(base[key])) {
      out.config[key] = { ...base[key], ...spec.config[key] };
    }
  }

  // A chart with no declared size renders at Vega's 200x200 default, which is
  // too small to read in the panel.
  if (out.width === undefined && !out.facet && !out.repeat && !out.concat) {
    out.width = "container" in out ? out.width : 540;
  }
  if (out.height === undefined && !out.facet && !out.repeat && !out.concat) {
    out.height = 320;
  }
  return out;
}
