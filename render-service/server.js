// Weave render sandbox.
//
// Turns AI-emitted *specs* into rendered assets. Every page it produces is
// fully self-contained: no CDN, no external font, no network at runtime.
//
//   POST /chart      { spec (Vega-Lite), format }   -> SVG / PNG
//   POST /deck       { slides, theme }              -> self-contained deck HTML
//   POST /three      { scene, theme }               -> Three.js page (scatter/bars/surface/network)
//   POST /diagram    { spec, theme }                -> SVG diagram (flow/tree/timeline/concept/wireframe)
//   POST /simulation { spec, theme }                -> interactive parameterised simulation
//   POST /animation  { spec, theme }                -> self-drawing animated SVG explainer
//   POST /custom     { code, html, libs, theme }    -> model-authored code under hard containment
//
// The first six are SPEC-DRIVEN: this service owns 100% of the rendering code
// and the caller's payload is only ever data. /custom is the deliberate escape
// hatch — see lib/custom.js for why that is safe and what actually contains it.
import express from "express";
import * as vega from "vega";
import * as vegaLite from "vega-lite";
import { readFileSync } from "node:fs";
import path from "node:path";
import { Resvg } from "@resvg/resvg-js";
import { renderDiagram } from "./lib/diagram.js";
import { renderSimulation } from "./lib/simulation.js";
import { renderAnimation } from "./lib/animation.js";
import { renderThree } from "./lib/three3d.js";
import { renderCustom } from "./lib/custom.js";

const app = express();
app.use(express.json({ limit: "8mb" }));

// Inline the Three.js UMD build once so 3D pages are fully self-contained (no CDN,
// CSP-safe). Read the file directly — three's package `exports` map blocks
// require.resolve of the build path.
let THREE_SRC = "";
for (const rel of ["node_modules/three/build/three.min.js", "node_modules/three/build/three.js"]) {
  try {
    THREE_SRC = readFileSync(path.join(process.cwd(), rel), "utf-8");
    if (THREE_SRC) break;
  } catch (e) { /* try next */ }
}
if (!THREE_SRC) console.warn("three build not found; /three will return a scaffold");

app.get("/health", (_req, res) => res.json({ status: "ok", service: "render", ts: null }));

// ---- charts: Vega-Lite spec -> SVG ----------------------------------------
app.post("/chart", async (req, res) => {
  try {
    const { spec, format = "svg" } = req.body || {};
    if (!spec) return res.status(400).json({ error: "missing spec" });
    const vgSpec = spec.$schema && spec.$schema.includes("vega-lite")
      ? vegaLite.compile(spec).spec
      : spec;
    const view = new vega.View(vega.parse(vgSpec), { renderer: "none" });
    const svg = await view.toSVG();
    if (format === "png") {
      // Rasterise SVG -> PNG in-process (resvg, Rust). No headless browser needed.
      const png = new Resvg(svg, { fitTo: { mode: "width", value: 1200 } })
        .render().asPng();
      res.json({ svg, png_base64: png.toString("base64") });
    } else if (format === "svg") {
      res.type("image/svg+xml").send(svg);
    } else {
      res.json({ svg });
    }
  } catch (e) {
    res.status(500).json({ error: String(e && e.message ? e.message : e) });
  }
});

// ---- decks: slides -> self-contained Reveal.js HTML -----------------------
function mdToHtml(md) {
  // intentionally tiny: headings, bold, lists, paragraphs. The model supplies
  // already-structured slide bodies; full markdown is a later enhancement.
  return md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^### (.*)$/gm, "<h3>$1</h3>")
    .replace(/^## (.*)$/gm, "<h2>$1</h2>")
    .replace(/^# (.*)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^- (.*)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>")
    .split(/\n{2,}/).map((b) => (b.startsWith("<") ? b : `<p>${b}</p>`)).join("\n");
}

app.post("/deck", (req, res) => {
  const { slides = [], title = "Weave deck", theme = "light" } = req.body || {};
  const bg = theme === "dark" ? "#0f172a" : "#f8fafc";
  const fg = theme === "dark" ? "#f1f5f9" : "#0f172a";
  const sections = slides.map((s) => {
    const head = s.title ? `<h2>${String(s.title)}</h2>` : "";
    return `<section>${head}${mdToHtml(String(s.body_md || ""))}</section>`;
  }).join("\n");
  // Self-contained: no external CDN (CSP-safe). Minimal deck styling + keyboard nav.
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title>
<style>
  html,body{margin:0;height:100%;background:${bg};color:${fg};font-family:system-ui,sans-serif}
  .deck{height:100%;overflow:hidden}
  section{display:none;height:100%;box-sizing:border-box;padding:6vh 8vw}
  section.active{display:block}
  h1,h2{color:#0d9488} li{margin:.3em 0}
  .nav{position:fixed;bottom:12px;right:16px;font-size:14px;opacity:.6}
</style></head><body>
<div class="deck">${sections}</div>
<div class="nav">← / → to navigate</div>
<script>
  const s=[...document.querySelectorAll('section')];let i=0;
  function show(n){s.forEach(x=>x.classList.remove('active'));i=Math.max(0,Math.min(s.length-1,n));if(s[i])s[i].classList.add('active')}
  document.addEventListener('keydown',e=>{if(e.key==='ArrowRight')show(i+1);if(e.key==='ArrowLeft')show(i-1)});
  show(0);
</script></body></html>`;
  res.type("text/html").send(html);
});

// ---- 3D ------------------------------------------------------------------
app.post("/three", (req, res) => {
  const { scene = {}, title = "Weave 3D", theme = "dark" } = req.body || {};
  try {
    res.json(renderThree({ scene, title, theme, threeSrc: THREE_SRC }));
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
});

// ---- 2D diagrams ---------------------------------------------------------
app.post("/diagram", (req, res) => {
  const { spec = {}, title = "Diagram", theme = "light" } = req.body || {};
  try {
    const out = renderDiagram({ spec, title, theme });
    res.status(out.status === "ok" ? 200 : 400).json(out);
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
});

// ---- interactive simulations ---------------------------------------------
app.post("/simulation", (req, res) => {
  const { spec = {}, title = "Simulation", theme = "light" } = req.body || {};
  try {
    const out = renderSimulation({ spec, title, theme });
    res.status(out.status === "ok" ? 200 : 400).json(out);
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
});

// ---- self-drawing explainers ---------------------------------------------
app.post("/animation", (req, res) => {
  const { spec = {}, title = "Explainer", theme = "light" } = req.body || {};
  try {
    const out = renderAnimation({ spec, title, theme });
    res.status(out.status === "ok" ? 200 : 400).json(out);
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
});

// ---- escape hatch: model-authored code -----------------------------------
app.post("/custom", (req, res) => {
  const { code = "", html = "", title = "Visual", theme = "light", libs = [] } = req.body || {};
  try {
    const out = renderCustom({ code, html, title, theme, libs, threeSrc: THREE_SRC });
    res.status(out.status === "ok" ? 200 : 400).json(out);
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
});


const PORT = process.env.PORT || 3100;
app.listen(PORT, () => console.log(`weave render-service on :${PORT}`));
