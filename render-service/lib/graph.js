// Knowledge graphs and node-edge diagrams, rendered with React Flow.
//
// This is a SPEC-DRIVEN endpoint: the model supplies nodes and edges as data and
// this service owns 100% of the rendering code. That is deliberate — a knowledge
// graph is the one visual a research assistant produces constantly, and letting
// the model hand-roll pan/zoom/layout every time guarantees eight different
// half-working implementations.
//
// React Flow ships ESM/CJS only, so there is no UMD bundle to inline the way we
// inline Babylon. `dist/weaveflow.js` is built by esbuild at image-build time
// (see package.json `build:flow`) and read once at boot by server.js.
//
// Layout is computed in the page rather than here so a node the user drags stays
// where they put it, and so `layout: "preset"` can honour coordinates the model
// supplies for a diagram whose geometry carries meaning.
import { TOKENS, esc, palette } from "./theme.js";

const LAYOUTS = new Set(["lr", "tb", "rl", "bt", "radial", "preset"]);

/**
 * @param spec.nodes  [{ id, label, group?, detail?, url?, kind?, x?, y? }]
 * @param spec.edges  [{ source, target, label?, kind?, animated? }]
 * @param spec.layout "lr" | "tb" | "rl" | "bt" | "radial" | "preset"
 */
export function renderGraph({
  spec = {},
  title = "Knowledge graph",
  subtitle = "",
  theme = "light",
  flowSrc = "",
  flowCss = "",
} = {}) {
  if (!flowSrc) {
    return {
      status: "unavailable",
      error:
        "React Flow is not bundled in this render service (run `npm run build:flow` " +
        "in render-service/, or rebuild the image).",
    };
  }

  const nodes = Array.isArray(spec.nodes) ? spec.nodes : [];
  const edges = Array.isArray(spec.edges) ? spec.edges : [];
  if (!nodes.length) {
    return { status: "error", error: "graph spec has no nodes" };
  }

  // Referential integrity is checked HERE rather than in the page: an edge that
  // points at a node that was never defined makes React Flow drop it silently,
  // and a silently incomplete graph is worse than a loud rejection.
  const ids = new Set(nodes.map((n) => String(n.id)));
  const dangling = edges.filter(
    (e) => !ids.has(String(e.source)) || !ids.has(String(e.target)),
  );
  if (dangling.length) {
    const sample = dangling
      .slice(0, 5)
      .map((e) => `${e.source} -> ${e.target}`)
      .join(", ");
    return {
      status: "error",
      error:
        `${dangling.length} edge(s) reference a node id that is not in \`nodes\`: ` +
        `${sample}. Every edge endpoint must match a node id exactly.`,
    };
  }

  const layout = LAYOUTS.has(String(spec.layout)) ? String(spec.layout) : "lr";
  const t = TOKENS[theme === "dark" ? "dark" : "light"];
  const colors = palette(theme);

  // Groups drive colour. Assigning here (not in the page) keeps the legend and
  // the nodes provably in sync.
  const groups = [];
  for (const n of nodes) {
    const g = n.group ? String(n.group) : "";
    if (g && !groups.includes(g)) groups.push(g);
  }
  const groupColor = {};
  groups.forEach((g, i) => {
    groupColor[g] = colors[i % colors.length];
  });

  const data = {
    nodes: nodes.map((n) => ({
      id: String(n.id),
      label: String(n.label ?? n.id),
      group: n.group ? String(n.group) : "",
      detail: n.detail ? String(n.detail) : "",
      url: n.url ? String(n.url) : "",
      kind: n.kind ? String(n.kind) : "concept",
      color: n.group ? groupColor[String(n.group)] : colors[0],
      x: Number.isFinite(n.x) ? Number(n.x) : null,
      y: Number.isFinite(n.y) ? Number(n.y) : null,
    })),
    edges: edges.map((e, i) => ({
      id: `e${i}`,
      source: String(e.source),
      target: String(e.target),
      label: e.label ? String(e.label) : "",
      kind: e.kind ? String(e.kind) : "",
      animated: Boolean(e.animated),
    })),
    layout,
    groups: groups.map((g) => ({ label: g, color: groupColor[g] })),
    tokens: {
      bg: t.bg,
      surface: t.surface,
      surface2: t.surface2,
      border: t.border,
      fg: t.fg,
      fgMuted: t.fgMuted,
      fgFaint: t.fgFaint,
      accent: t.accent,
      grid: t.grid,
    },
  };

  const html = pageHtml({
    title,
    subtitle,
    theme,
    caption: spec.caption ? String(spec.caption) : "",
    flowSrc,
    flowCss,
    data,
  });

  return {
    status: "ok",
    html,
    node_count: data.nodes.length,
    edge_count: data.edges.length,
  };
}

function pageHtml({ title, subtitle, theme, caption, flowSrc, flowCss, data }) {
  const t = TOKENS[theme === "dark" ? "dark" : "light"];
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>${esc(title)}</title>
<style>
${flowCss}
:root{
  --bg:${t.bg};--surface:${t.surface};--surface-2:${t.surface2};--border:${t.border};
  --fg:${t.fg};--fg-muted:${t.fgMuted};--fg-faint:${t.fgFaint};--accent:${t.accent};--grid:${t.grid};
}
*{box-sizing:border-box}
html,body,#root{height:100%;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);
  font-family:ui-monospace,"JetBrains Mono","SFMono-Regular",Menlo,Consolas,monospace;
  -webkit-font-smoothing:antialiased;overflow:hidden}
.shell{display:flex;flex-direction:column;height:100%}
header{padding:12px 16px 10px;border-bottom:1px solid var(--border);flex:0 0 auto}
.eyebrow{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--fg-faint)}
h1{font-size:17px;font-weight:600;letter-spacing:-.01em;margin:.2em 0 0;line-height:1.2}
p.sub{color:var(--fg-muted);font-size:12px;line-height:1.5;margin:.4em 0 0;max-width:80ch}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:8px}
.legend span{display:inline-flex;align-items:center;gap:6px;font-size:10.5px;color:var(--fg-muted)}
.legend i{width:9px;height:9px;display:inline-block}
.body{flex:1 1 auto;position:relative;min-height:0}
.toolbar{position:absolute;z-index:6;top:10px;left:10px;display:flex;gap:6px;align-items:center}
.toolbar input{background:var(--surface);border:1px solid var(--border);color:var(--fg);
  padding:5px 8px;font:inherit;font-size:11.5px;width:170px}
.toolbar input::placeholder{color:var(--fg-faint)}
.btn{background:var(--surface);border:1px solid var(--border);color:var(--fg);
  padding:5px 9px;font:inherit;font-size:11.5px;cursor:pointer}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.panel{position:absolute;z-index:6;right:10px;top:10px;width:250px;max-height:calc(100% - 20px);
  overflow:auto;background:var(--surface);border:1px solid var(--border);padding:12px 13px}
.panel h2{font-size:12.5px;margin:0 0 6px;font-weight:600;line-height:1.3}
.panel .k{font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--fg-faint)}
.panel p{font-size:11.5px;line-height:1.6;color:var(--fg-muted);margin:6px 0 0;
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.panel a{color:var(--accent);font-size:11px;word-break:break-all}
.panel .close{position:absolute;top:8px;right:9px;background:none;border:0;color:var(--fg-faint);
  cursor:pointer;font-size:14px;line-height:1;padding:2px 4px}
.wnode{border:1px solid var(--border);background:var(--surface);padding:7px 10px;
  min-width:90px;max-width:190px;font-size:11.5px;line-height:1.35;color:var(--fg);
  border-left-width:3px;cursor:pointer}
.wnode.dim{opacity:.22}
.wnode.hit{border-color:var(--accent)}
.wnode .lbl{font-weight:500;word-break:break-word}
.wnode .grp{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--fg-faint);margin-top:3px}
.react-flow__edge-text{font-size:9.5px;fill:var(--fg-faint);
  font-family:ui-monospace,Consolas,monospace}
.react-flow__attribution{display:none}
footer{flex:0 0 auto;padding:8px 16px;border-top:1px solid var(--border);
  font-size:11px;color:var(--fg-muted);line-height:1.5}
@media (max-width:640px){
  .panel{right:8px;left:8px;width:auto;top:auto;bottom:8px;max-height:46%}
  .toolbar input{width:120px}
}
@media (prefers-reduced-motion:reduce){*{animation-duration:.01ms!important;transition-duration:.01ms!important}}
</style></head>
<body>
<div class="shell">
  <header>
    <div class="eyebrow">Weave</div>
    <h1>${esc(title)}</h1>
    ${subtitle ? `<p class="sub">${esc(subtitle)}</p>` : ""}
    <div class="legend" id="legend"></div>
  </header>
  <div class="body"><div id="root"></div></div>
  ${caption ? `<footer>${esc(caption)}</footer>` : ""}
</div>
<script>${flowSrc}</script>
<script id="graph-data" type="application/json">${jsonForScript(data)}</script>
<script>${RUNTIME}</script>
</body></html>`;
}

/**
 * Embed JSON inside a <script> without letting a "</script>" inside a label end
 * the block early. Reading it from a `type="application/json"` block rather than
 * assigning it into JS source also means no amount of odd punctuation in a node
 * label can become executable.
 */
function jsonForScript(obj) {
  // Only `<` and `>` genuinely matter here: the block is parsed as JSON, not as
  // JavaScript source, so once the tag cannot be closed early nothing inside a
  // label can escape into code.
  return JSON.stringify(obj).replace(/</g, "\\u003c").replace(/>/g, "\\u003e");
}

// The page runtime. Plain ES5-ish source, no build step, no template literals —
// it is inlined into a <script> tag, so a stray backtick would be a live bug
// rather than a compile error.
const RUNTIME = `
(function () {
  var W = window.WeaveFlow;
  if (!W) { document.getElementById('root').textContent = 'graph runtime failed to load'; return; }
  var React = W.React, RF = W.ReactFlow, dagre = W.dagre;
  var h = React.createElement;
  var DATA = JSON.parse(document.getElementById('graph-data').textContent);

  /* ---- layout ---------------------------------------------------------- */
  var NODE_W = 172, NODE_H = 46;

  function dagreLayout(nodes, edges, dir) {
    var g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: dir, nodesep: 28, ranksep: 74, marginx: 28, marginy: 28 });
    g.setDefaultEdgeLabel(function () { return {}; });
    nodes.forEach(function (n) { g.setNode(n.id, { width: NODE_W, height: NODE_H }); });
    edges.forEach(function (e) { g.setEdge(e.source, e.target); });
    dagre.layout(g);
    var pos = {};
    nodes.forEach(function (n) {
      var p = g.node(n.id);
      pos[n.id] = { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 };
    });
    return pos;
  }

  function radialLayout(nodes, edges) {
    /* Degree picks the hub: in a knowledge graph the most-connected concept is
       almost always the one the reader should start from. */
    var deg = {};
    nodes.forEach(function (n) { deg[n.id] = 0; });
    edges.forEach(function (e) { deg[e.source]++; deg[e.target]++; });
    var sorted = nodes.slice().sort(function (a, b) { return deg[b.id] - deg[a.id]; });
    var pos = {}, hub = sorted[0];
    pos[hub.id] = { x: 0, y: 0 };
    var rest = sorted.slice(1);
    var ring = Math.max(1, Math.ceil(rest.length / 12));
    rest.forEach(function (n, i) {
      var band = Math.floor(i / 12);
      var inBand = rest.slice(band * 12, band * 12 + 12).length;
      var idx = i - band * 12;
      var r = 210 + band * 175;
      var a = (idx / inBand) * Math.PI * 2 - Math.PI / 2;
      pos[n.id] = { x: Math.cos(a) * r, y: Math.sin(a) * r * (ring > 1 ? 0.82 : 1) };
    });
    return pos;
  }

  function computePositions() {
    var L = DATA.layout;
    if (L === 'preset') {
      var pos = {};
      DATA.nodes.forEach(function (n, i) {
        pos[n.id] = { x: n.x == null ? (i % 6) * 210 : n.x, y: n.y == null ? Math.floor(i / 6) * 120 : n.y };
      });
      return pos;
    }
    if (L === 'radial') return radialLayout(DATA.nodes, DATA.edges);
    var dir = L === 'tb' ? 'TB' : L === 'bt' ? 'BT' : L === 'rl' ? 'RL' : 'LR';
    return dagreLayout(DATA.nodes, DATA.edges, dir);
  }

  /* ---- custom node ----------------------------------------------------- */
  function WeaveNode(props) {
    var d = props.data;
    var cls = 'wnode' + (d.dim ? ' dim' : '') + (d.hit ? ' hit' : '');
    return h('div', { className: cls, style: { borderLeftColor: d.color }, title: d.detail || d.label },
      h(RF.Handle, { type: 'target', position: RF.Position.Left, style: { opacity: 0 } }),
      h('div', { className: 'lbl' }, d.label),
      d.group ? h('div', { className: 'grp' }, d.group) : null,
      h(RF.Handle, { type: 'source', position: RF.Position.Right, style: { opacity: 0 } })
    );
  }
  var NODE_TYPES = { weave: WeaveNode };

  /* ---- app ------------------------------------------------------------- */
  function App() {
    var positions = React.useMemo(computePositions, []);
    var tk = DATA.tokens;

    var initialNodes = React.useMemo(function () {
      return DATA.nodes.map(function (n) {
        return {
          id: n.id,
          type: 'weave',
          position: positions[n.id] || { x: 0, y: 0 },
          data: { label: n.label, group: n.group, detail: n.detail, url: n.url, color: n.color },
        };
      });
    }, [positions]);

    var initialEdges = React.useMemo(function () {
      return DATA.edges.map(function (e) {
        return {
          id: e.id, source: e.source, target: e.target, label: e.label,
          type: 'smoothstep', animated: e.animated,
          markerEnd: { type: RF.MarkerType.ArrowClosed, width: 15, height: 15, color: tk.fgFaint },
          style: { stroke: tk.fgFaint, strokeWidth: 1.1 },
        };
      });
    }, []);

    var ns = RF.useNodesState(initialNodes);
    var nodes = ns[0], setNodes = ns[1], onNodesChange = ns[2];
    var es = RF.useEdgesState(initialEdges);
    var edges = es[0], onEdgesChange = es[2];

    var sel = React.useState(null); var selected = sel[0], setSelected = sel[1];
    var qs = React.useState(''); var query = qs[0], setQuery = qs[1];

    /* Search dims rather than filters. Removing non-matching nodes destroys the
       structure that makes a graph worth looking at; dimming keeps the shape
       visible while the match stands out. */
    React.useEffect(function () {
      var q = query.trim().toLowerCase();
      setNodes(function (cur) {
        return cur.map(function (n) {
          var hit = q ? (n.data.label + ' ' + (n.data.group || '') + ' ' + (n.data.detail || '')).toLowerCase().indexOf(q) >= 0 : false;
          if (!!n.data.dim === (q ? !hit : false) && !!n.data.hit === hit) return n;
          return Object.assign({}, n, { data: Object.assign({}, n.data, { dim: q ? !hit : false, hit: hit }) });
        });
      });
    }, [query, setNodes]);

    var onNodeClick = React.useCallback(function (_e, node) { setSelected(node); }, []);

    return h('div', { style: { width: '100%', height: '100%' } },
      h('div', { className: 'toolbar' },
        h('input', {
          placeholder: 'Find a node', value: query, 'aria-label': 'Find a node',
          onChange: function (e) { setQuery(e.target.value); },
        }),
        query ? h('button', { className: 'btn', onClick: function () { setQuery(''); } }, 'Clear') : null
      ),
      selected ? h('div', { className: 'panel' },
        h('button', { className: 'close', onClick: function () { setSelected(null); }, 'aria-label': 'Close' }, '\\u00d7'),
        selected.data.group ? h('div', { className: 'k' }, selected.data.group) : null,
        h('h2', null, selected.data.label),
        selected.data.detail ? h('p', null, selected.data.detail) : null,
        selected.data.url ? h('p', null, h('a', { href: selected.data.url, target: '_blank', rel: 'noopener noreferrer' }, selected.data.url)) : null
      ) : null,
      h(RF.default, {
        nodes: nodes, edges: edges,
        onNodesChange: onNodesChange, onEdgesChange: onEdgesChange,
        nodeTypes: NODE_TYPES, onNodeClick: onNodeClick,
        fitView: true, fitViewOptions: { padding: 0.18 },
        minZoom: 0.08, maxZoom: 2.5,
        proOptions: { hideAttribution: true },
        nodesConnectable: false, elevateEdgesOnSelect: true,
      },
        h(RF.Background, { color: tk.grid, gap: 22, size: 1 }),
        h(RF.Controls, { showInteractive: false }),
        h(RF.MiniMap, {
          pannable: true, zoomable: true,
          style: { background: tk.surface2, border: '1px solid ' + tk.border },
          maskColor: DATA.tokens.bg === '#0c0b0a' ? 'rgba(12,11,10,.72)' : 'rgba(255,255,255,.66)',
          nodeColor: function (n) { return n.data && n.data.color ? n.data.color : tk.fgFaint; },
        })
      )
    );
  }

  /* legend is plain DOM: it lives outside the canvas and never re-renders */
  var lg = document.getElementById('legend');
  DATA.groups.forEach(function (g) {
    var s = document.createElement('span');
    var i = document.createElement('i');
    i.style.background = g.color;
    s.appendChild(i);
    s.appendChild(document.createTextNode(g.label));
    lg.appendChild(s);
  });

  W.createRoot(document.getElementById('root')).render(
    h(RF.ReactFlowProvider, null, h(App))
  );
})();
`;
