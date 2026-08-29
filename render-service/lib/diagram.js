// Spec -> SVG diagrams.
//
// Most of what a student actually needs is 2D and structural: how the steps
// connect, what contains what, what happened when. Those do not need WebGL and
// should not pay for it — these render as plain SVG, so they are crisp at any
// zoom, printable, tiny, and work with no scripting at all.
//
// Layout is computed here rather than asked of the model: a model is good at
// saying "A leads to B and C", and bad at picking non-overlapping coordinates.

import { esc, page, palette, TOKENS } from "./theme.js";
import { svgHasContent } from "./js.js";

const PAD = 28;

/* ------------------------------------------------------------------ layout */

/**
 * Layer nodes by longest-path depth from the roots.
 * Cycles are tolerated: a node already on the current path is not re-visited,
 * so a circular spec degrades to a sensible layering instead of hanging.
 */
function layerNodes(nodes, edges) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const outgoing = new Map(nodes.map((n) => [n.id, []]));
  const indeg = new Map(nodes.map((n) => [n.id, 0]));
  for (const e of edges) {
    if (!byId.has(e.from) || !byId.has(e.to)) continue;
    outgoing.get(e.from).push(e.to);
    indeg.set(e.to, indeg.get(e.to) + 1);
  }
  const depth = new Map(nodes.map((n) => [n.id, 0]));
  const roots = nodes.filter((n) => indeg.get(n.id) === 0).map((n) => n.id);
  const queue = roots.length ? [...roots] : [nodes[0]?.id].filter(Boolean);
  const seenAt = new Map();
  let guard = 0;
  while (queue.length && guard++ < 10000) {
    const id = queue.shift();
    const d = depth.get(id) ?? 0;
    for (const next of outgoing.get(id) ?? []) {
      if (seenAt.get(next) === d + 1) continue;
      if ((depth.get(next) ?? 0) < d + 1) {
        depth.set(next, d + 1);
        seenAt.set(next, d + 1);
        queue.push(next);
      }
    }
  }
  const layers = [];
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0;
    (layers[d] ||= []).push(n);
  }
  return layers.filter(Boolean);
}

function measure(text, size) {
  // Approximate advance width. Good enough to size a box without a font metric
  // table, and consistently slightly generous so text never overflows.
  return String(text ?? "").length * size * 0.56;
}

/* ------------------------------------------------------------------ shapes */

function nodeBox(n, x, y, w, h, colour, t) {
  const shape = n.shape || "box";
  const label = esc(n.label ?? n.id);
  const sub = n.sub ? esc(n.sub) : "";
  const cy = y + h / 2;
  let outline;
  if (shape === "round") {
    outline = `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${h / 2}" fill="${t.surface}" stroke="${colour}" stroke-width="1.5"/>`;
  } else if (shape === "diamond") {
    const mx = x + w / 2;
    outline = `<polygon points="${mx},${y} ${x + w},${cy} ${mx},${y + h} ${x},${cy}" fill="${t.surface}" stroke="${colour}" stroke-width="1.5"/>`;
  } else if (shape === "circle") {
    const r = Math.min(w, h) / 2;
    outline = `<circle cx="${x + w / 2}" cy="${cy}" r="${r}" fill="${t.surface}" stroke="${colour}" stroke-width="1.5"/>`;
  } else if (shape === "note") {
    outline = `<path d="M${x} ${y} H${x + w - 12} L${x + w} ${y + 12} V${y + h} H${x} Z" fill="${t.surface}" stroke="${colour}" stroke-width="1.5"/>`;
  } else {
    outline = `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${t.surface}" stroke="${colour}" stroke-width="1.5"/>`;
  }
  const textY = sub ? cy - 4 : cy + 1;
  return `<g>${outline}
<text x="${x + w / 2}" y="${textY}" text-anchor="middle" dominant-baseline="middle"
  font-size="13" font-family="ui-sans-serif,system-ui,sans-serif" fill="${t.fg}">${label}</text>
${sub ? `<text x="${x + w / 2}" y="${cy + 12}" text-anchor="middle" dominant-baseline="middle" font-size="10.5" font-family="ui-monospace,monospace" fill="${t.fgFaint}">${sub}</text>` : ""}
</g>`;
}

function arrow(x1, y1, x2, y2, colour, label, t, curved) {
  const d = curved
    ? `M${x1} ${y1} C ${x1} ${(y1 + y2) / 2}, ${x2} ${(y1 + y2) / 2}, ${x2} ${y2}`
    : `M${x1} ${y1} L${x2} ${y2}`;
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  return `<path d="${d}" fill="none" stroke="${colour}" stroke-width="1.2" marker-end="url(#arw)"/>
${label ? `<rect x="${mx - measure(label, 10) / 2 - 4}" y="${my - 8}" width="${measure(label, 10) + 8}" height="15" fill="${t.bg}"/><text x="${mx}" y="${my + 3}" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace" fill="${t.fgMuted}">${esc(label)}</text>` : ""}`;
}

/* ------------------------------------------------------------------- kinds */

function renderFlow(spec, t, cols, vertical) {
  const nodes = (spec.nodes || []).slice(0, 60);
  const edges = (spec.edges || []).slice(0, 120);
  if (!nodes.length) return { svg: "", w: 400, h: 120 };

  const layers = layerNodes(nodes, edges);
  const gapX = 46;
  const gapY = 54;
  const h = 44;
  const pos = new Map();

  // Size each layer to its widest label so nothing is clipped.
  const layerW = layers.map((l) =>
    Math.max(...l.map((n) => Math.max(120, measure(n.label ?? n.id, 13) + 34))),
  );

  let w = 0;
  let H = 0;
  if (vertical) {
    const rowW = layers.map((l, i) => l.length * layerW[i] + (l.length - 1) * gapX);
    w = Math.max(...rowW) + PAD * 2;
    H = layers.length * h + (layers.length - 1) * gapY + PAD * 2;
    layers.forEach((l, li) => {
      const total = l.length * layerW[li] + (l.length - 1) * gapX;
      let x = (w - total) / 2;
      const y = PAD + li * (h + gapY);
      for (const n of l) {
        pos.set(n.id, { x, y, w: layerW[li], h });
        x += layerW[li] + gapX;
      }
    });
  } else {
    const colH = layers.map((l) => l.length * h + (l.length - 1) * gapY);
    H = Math.max(...colH) + PAD * 2;
    w = layerW.reduce((a, b) => a + b, 0) + (layers.length - 1) * gapX + PAD * 2;
    let x = PAD;
    layers.forEach((l, li) => {
      let y = (H - colH[li]) / 2;
      for (const n of l) {
        pos.set(n.id, { x, y, w: layerW[li], h });
        y += h + gapY;
      }
      x += layerW[li] + gapX;
    });
  }

  const parts = [];
  for (const e of edges) {
    const a = pos.get(e.from);
    const b = pos.get(e.to);
    if (!a || !b) continue;
    const [x1, y1, x2, y2] = vertical
      ? [a.x + a.w / 2, a.y + a.h, b.x + b.w / 2, b.y]
      : [a.x + a.w, a.y + a.h / 2, b.x, b.y + b.h / 2];
    parts.push(arrow(x1, y1, x2, y2, t.fgFaint, e.label, t, true));
  }
  nodes.forEach((n, i) => {
    const p = pos.get(n.id);
    if (!p) return;
    const colour = n.accent ? t.accent : cols[i % cols.length];
    parts.push(nodeBox(n, p.x, p.y, p.w, p.h, colour, t));
  });
  return { svg: parts.join("\n"), w, h: H };
}

function renderTimeline(spec, t, cols) {
  const items = (spec.items || spec.nodes || []).slice(0, 40);
  const rowH = 62;
  const w = 860;
  const h = PAD * 2 + items.length * rowH;
  const axisX = 150;
  const parts = [
    `<line x1="${axisX}" y1="${PAD}" x2="${axisX}" y2="${h - PAD}" stroke="${t.border}" stroke-width="2"/>`,
  ];
  items.forEach((it, i) => {
    const y = PAD + i * rowH + 18;
    const colour = it.accent ? t.accent : cols[i % cols.length];
    parts.push(`<circle cx="${axisX}" cy="${y}" r="5" fill="${t.bg}" stroke="${colour}" stroke-width="2"/>`);
    parts.push(
      `<text x="${axisX - 16}" y="${y + 4}" text-anchor="end" font-size="11" font-family="ui-monospace,monospace" fill="${t.fgFaint}">${esc(it.when ?? it.sub ?? "")}</text>`,
    );
    parts.push(
      `<text x="${axisX + 18}" y="${y + 1}" font-size="13.5" font-family="ui-sans-serif,system-ui,sans-serif" fill="${t.fg}">${esc(it.label ?? it.title ?? "")}</text>`,
    );
    if (it.detail) {
      parts.push(
        `<text x="${axisX + 18}" y="${y + 18}" font-size="11.5" font-family="ui-sans-serif,system-ui,sans-serif" fill="${t.fgMuted}">${esc(String(it.detail).slice(0, 96))}</text>`,
      );
    }
  });
  return { svg: parts.join("\n"), w, h };
}

function renderHierarchy(spec, t, cols) {
  // A tree is a flow with vertical layering; reuse the layout wholesale.
  return renderFlow(spec, t, cols, true);
}

function renderConceptMap(spec, t, cols) {
  // Radial: the first node is the hub, the rest orbit it. Good for "what
  // relates to what" where there is no direction of flow.
  const nodes = (spec.nodes || []).slice(0, 24);
  if (!nodes.length) return { svg: "", w: 400, h: 200 };
  const [hub, ...rest] = nodes;
  const R = Math.max(140, 26 * rest.length);
  const w = R * 2 + 240;
  const h = R * 2 + 140;
  const cx = w / 2;
  const cy = h / 2;
  const parts = [];
  const boxW = 130;
  const boxH = 40;
  rest.forEach((n, i) => {
    const a = (i / rest.length) * Math.PI * 2 - Math.PI / 2;
    const x = cx + Math.cos(a) * R - boxW / 2;
    const y = cy + Math.sin(a) * R - boxH / 2;
    parts.push(
      `<line x1="${cx}" y1="${cy}" x2="${x + boxW / 2}" y2="${y + boxH / 2}" stroke="${t.border}" stroke-width="1.2"/>`,
    );
    parts.push(nodeBox(n, x, y, boxW, boxH, cols[i % cols.length], t));
  });
  parts.push(nodeBox({ ...hub, shape: hub.shape || "round" }, cx - 80, cy - 24, 160, 48, t.accent, t));
  return { svg: parts.join("\n"), w, h };
}

function renderWireframe(spec, t) {
  // A 12-column grid of blocks — enough to communicate a layout without
  // pretending to be a design tool.
  const blocks = (spec.blocks || spec.nodes || []).slice(0, 40);
  const cols = 12;
  const unit = 62;
  const rowH = spec.row_height || 54;
  const w = cols * unit + PAD * 2;
  let maxRow = 0;
  const parts = [];
  blocks.forEach((b) => {
    const c = Math.max(0, Math.min(cols - 1, b.col ?? 0));
    const span = Math.max(1, Math.min(cols - c, b.span ?? 12));
    const row = b.row ?? 0;
    const rspan = Math.max(1, b.row_span ?? 1);
    maxRow = Math.max(maxRow, row + rspan);
    const x = PAD + c * unit;
    const y = PAD + row * rowH;
    const bw = span * unit - 8;
    const bh = rspan * rowH - 8;
    const isAccent = Boolean(b.accent);
    parts.push(
      `<rect x="${x}" y="${y}" width="${bw}" height="${bh}" fill="${isAccent ? t.accentSoft : t.surface2}" stroke="${isAccent ? t.accent : t.border}" stroke-width="1.2"/>`,
    );
    if (b.label) {
      parts.push(
        `<text x="${x + 10}" y="${y + 19}" font-size="11.5" font-family="ui-monospace,monospace" fill="${t.fgMuted}">${esc(b.label)}</text>`,
      );
    }
    // Placeholder text lines, the universal wireframe idiom.
    if (b.lines) {
      for (let i = 0; i < Math.min(6, b.lines); i++) {
        const ly = y + 34 + i * 11;
        if (ly > y + bh - 8) break;
        parts.push(
          `<rect x="${x + 10}" y="${ly}" width="${(bw - 20) * (i % 3 === 2 ? 0.6 : 0.92)}" height="4" fill="${t.border}"/>`,
        );
      }
    }
  });
  return { svg: parts.join("\n"), w, h: PAD * 2 + maxRow * rowH };
}

/* -------------------------------------------------------------------- main */

const KINDS = {
  flow: (s, t, c) => renderFlow(s, t, c, false),
  flowchart: (s, t, c) => renderFlow(s, t, c, false),
  vflow: (s, t, c) => renderFlow(s, t, c, true),
  hierarchy: renderHierarchy,
  tree: renderHierarchy,
  timeline: renderTimeline,
  concept: renderConceptMap,
  concept_map: renderConceptMap,
  mindmap: renderConceptMap,
  wireframe: renderWireframe,
};

export function renderDiagram({ spec = {}, title = "Diagram", theme = "light" }) {
  const t = TOKENS[theme === "dark" ? "dark" : "light"];
  const cols = palette(theme);
  const kind = String(spec.kind || "flow").toLowerCase();
  const fn = KINDS[kind] || KINDS.flow;

  const { svg, w, h } = fn(spec, t, cols);
  if (!svg) {
    return { status: "error", error: `diagram spec has no nodes (kind="${kind}")` };
  }

  const inner = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${Math.round(w)} ${Math.round(h)}"
  width="100%" style="max-width:${Math.round(w)}px;height:auto;display:block" role="img"
  aria-label="${esc(title)}">
  <defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"
    orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${t.fgFaint}"/></marker></defs>
  <rect width="100%" height="100%" fill="${t.bg}"/>
  ${svg}
</svg>`;

  /*
    A diagram whose only content is its own background is not a diagram.

    The `!svg` check above catches an empty node list, which is the obvious
    case. It does not catch a spec whose nodes all fail to lay out -- edges
    referencing ids that do not exist, a timeline whose entries have no dates, a
    hierarchy with no root -- where the generator returns markup that is
    structurally fine and visually empty. Those reach the user as a blank framed
    box that took thirty seconds to produce and says nothing.
  */
  if (!svgHasContent(inner)) {
    return {
      status: "error",
      error:
        `the ${kind} diagram rendered with nothing in it. The nodes were accepted ` +
        `but none of them produced anything to draw -- usually edges pointing at ` +
        `ids that do not exist in \`nodes\`, or nodes with no label. Check that ` +
        `every edge's \`from\` and \`to\` matches a node id exactly.`,
    };
  }

  const html = page({
    title,
    subtitle: spec.description,
    theme,
    caption: spec.caption,
    body: `<div style="overflow-x:auto">${inner}</div>`,
  });

  return { status: "ok", kind, html, svg: inner, width: Math.round(w), height: Math.round(h) };
}
