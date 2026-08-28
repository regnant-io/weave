// Weave render sandbox.
//
// Turns AI-emitted *specs* into rendered assets. Every page it produces is
// fully self-contained: no CDN, no external font, no network at runtime.
//
//   POST /chart      { spec (Vega-Lite), format }   -> SVG / PNG
//   POST /deck       { slides, theme }              -> designed, self-contained deck HTML
//   POST /three      { scene, theme }               -> Three.js page (scatter/bars/surface/network)
//   POST /diagram    { spec, theme }                -> SVG diagram (flow/tree/timeline/concept/wireframe)
//   POST /simulation { spec, theme }                -> interactive parameterised simulation
//   POST /animation  { spec, theme }                -> self-drawing animated SVG explainer
//   POST /babylon    { code, assets, theme }        -> Babylon.js scene (games, 3D building)
//   POST /custom     { code, html, libs, theme }    -> model-authored code under hard containment
//
// The first six are SPEC-DRIVEN: this service owns 100% of the rendering code
// and the caller's payload is only ever data. /babylon and /custom are the
// deliberate escape hatches — there is no schema for "a game", and inventing one
// would only ever cover what we thought of first. See lib/custom.js for why that
// is safe and what actually contains it.
import express from "express";
import * as vega from "vega";
import * as vegaLite from "vega-lite";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Resvg } from "@resvg/resvg-js";
import { renderDiagram } from "./lib/diagram.js";
import { renderSimulation } from "./lib/simulation.js";
import { renderAnimation } from "./lib/animation.js";
import { renderThree } from "./lib/three3d.js";
import { renderCustom } from "./lib/custom.js";
import { renderBabylon } from "./lib/babylon.js";
import { renderGraph } from "./lib/graph.js";
import { renderHtmlPage } from "./lib/htmlpage.js";
import { lintHtml } from "./lib/js.js";
import { renderDeck } from "./lib/deck.js";
import { applyTheme } from "./lib/vegaTheme.js";

const app = express();
// Babylon scenes can carry inlined .glb meshes and textures as data URLs, which
// is the only way an offline artifact can use them at all.
app.use(express.json({ limit: "48mb" }));

// Resolve bundles relative to THIS FILE, not the working directory. `npm start`
// happens to run with cwd=/app, so a cwd-relative read worked by luck; anything
// that starts the server from elsewhere silently lost every optional engine and
// reported "babylon unavailable" with no indication why.
const HERE = path.dirname(fileURLToPath(import.meta.url));

/** Read the first readable path, or "" — a missing bundle degrades, never throws. */
function readFirst(rels) {
  for (const rel of rels) {
    try {
      const src = readFileSync(path.resolve(HERE, rel), "utf-8");
      if (src) return src;
    } catch (e) { /* try next */ }
  }
  return "";
}

// Inline the UMD builds once at boot so generated pages are fully self-contained
// (no CDN, CSP-safe). Read the files directly — these packages' `exports` maps
// block require.resolve of the build paths.
const THREE_SRC = readFirst([
  "node_modules/three/build/three.min.js",
  "node_modules/three/build/three.js",
]);
if (!THREE_SRC) console.warn("three build not found; /three will return a scaffold");

const BABYLON_SRC = readFirst([
  "node_modules/babylonjs/babylon.js",
  "node_modules/babylonjs/babylon.max.js",
]);
// Loaders (glTF/OBJ/STL) and GUI are separate bundles; both are optional, and a
// scene that does not import a mesh has no reason to pay for them.
const BABYLON_LOADERS_SRC = readFirst([
  "node_modules/babylonjs-loaders/babylonjs.loaders.min.js",
  "node_modules/babylonjs-loaders/babylonjs.loaders.js",
]);
const BABYLON_GUI_SRC = readFirst([
  "node_modules/babylonjs-gui/babylon.gui.min.js",
  "node_modules/babylonjs-gui/babylon.gui.js",
]);
if (!BABYLON_SRC) console.warn("babylon build not found; /babylon will report unavailable");

// React Flow has no UMD build, so it is bundled to an IIFE by esbuild during the
// image build (`npm run build:flow`). Its stylesheet is read straight from the
// package — inlining it is what makes a graph artifact work offline.
const FLOW_SRC = readFirst(["dist/weaveflow.js"]);
const FLOW_CSS = readFirst([
  "node_modules/reactflow/dist/style.css",
  "node_modules/reactflow/dist/base.css",
]);
if (!FLOW_SRC) console.warn("react-flow bundle not found; run `npm run build:flow`");

// Package version, read at boot. A stale container reporting an old version here
// is the difference between "why is Babylon missing" and "this image is old" —
// which is exactly the diagnosis that was missing before.
const PKG = (() => {
  try {
    return JSON.parse(readFileSync(path.resolve(HERE, "package.json"), "utf-8"));
  } catch { return { version: "unknown" }; }
})();

const ENGINES = {
  vega: true,
  three: Boolean(THREE_SRC),
  babylon: Boolean(BABYLON_SRC),
  babylon_loaders: Boolean(BABYLON_LOADERS_SRC),
  babylon_gui: Boolean(BABYLON_GUI_SRC),
  flow: Boolean(FLOW_SRC),
  html: true,
};

app.get("/health", (_req, res) => res.json({
  status: "ok",
  service: "render",
  version: PKG.version,
  // Report which optional bundles are actually present, so the backend can
  // advertise only the capabilities that will really work.
  engines: ENGINES,
  // Named explicitly so an operator can see WHICH engine is missing without
  // reading container logs.
  missing: Object.entries(ENGINES).filter(([, v]) => !v).map(([k]) => k),
}));

// ---- charts: Vega-Lite spec -> SVG ----------------------------------------
app.post("/chart", async (req, res) => {
  try {
    const { spec, format = "svg", theme = "light" } = req.body || {};
    if (!spec) return res.status(400).json({ error: "missing spec" });
    // House style is applied here rather than asked for in a prompt: charts that
    // each look fine but share no visual language read as amateur, and Vega's
    // own defaults (blue, cramped labels, dark gridlines, a box border) are not
    // a design. The caller's own `config` still wins — see lib/vegaTheme.js.
    const themed = applyTheme(spec, theme);
    const vgSpec = themed.$schema && themed.$schema.includes("vega-lite")
      ? vegaLite.compile(themed).spec
      : themed;
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

// ---- decks: slides -> self-contained, designed HTML deck ------------------
// See lib/deck.js: per-slide-shape layouts, the shared Weave type scale, touch
// + keyboard navigation, and a print stylesheet so browser "Save as PDF"
// produces a real landscape deck without needing Gotenberg.
app.post("/deck", (req, res) => {
  const { slides = [], title = "Weave deck", subtitle = "", theme = "light" } = req.body || {};
  try {
    const out = renderDeck({ slides, title, subtitle, theme });
    if (out.status !== "ok") return res.status(400).json(out);
    res.type("text/html").send(out.html);
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
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

// ---- Babylon.js: games, 3D builders, interactive scenes -------------------
// Model-authored scene code, contained the same way /custom is (opaque-origin
// iframe + strict CSP). Assets travel inline as data URLs because the artifact
// has no network at runtime.
app.post("/babylon", (req, res) => {
  const {
    code = "", title = "3D scene", subtitle = "", theme = "dark",
    assets = {}, physics = false, controls = "", libs = [],
  } = req.body || {};
  try {
    const wantsLoaders = libs.includes("loaders") || /SceneLoader|ImportMesh|glTF/i.test(code);
    const wantsGui = libs.includes("gui") || /BABYLON\.GUI/.test(code);
    const out = renderBabylon({
      code, title, subtitle, theme, assets, physics, controls,
      babylonSrc: BABYLON_SRC,
      loadersSrc: wantsLoaders ? BABYLON_LOADERS_SRC : "",
      guiSrc: wantsGui ? BABYLON_GUI_SRC : "",
    });
    res.status(out.status === "ok" ? 200 : 400).json(out);
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
});

// ---- knowledge graphs: React Flow ----------------------------------------
// Spec-driven on purpose. A node-edge graph is the visual a research assistant
// reaches for most often, and hand-rolling pan/zoom/layout per request produces
// a different half-working implementation every time.
app.post("/graph", (req, res) => {
  const { spec = {}, title = "Knowledge graph", subtitle = "", theme = "light" } = req.body || {};
  try {
    const out = renderGraph({ spec, title, subtitle, theme, flowSrc: FLOW_SRC, flowCss: FLOW_CSS });
    res.status(out.status === "ok" ? 200 : 400).json(out);
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
});

// ---- single-file HTML pages ----------------------------------------------
// Validates and repairs a complete page the model wrote (see lib/htmlpage.js).
app.post("/html", (req, res) => {
  const { html = "", title = "Page", strict = false } = req.body || {};
  try {
    const out = renderHtmlPage({ html, title, strict });
    res.status(out.status === "ok" ? 200 : 400).json(out);
  } catch (e) {
    res.status(500).json({ status: "error", error: String(e?.message ?? e) });
  }
});

// ---- verification --------------------------------------------------------
// Read-only static check, so the assistant can confirm a page it just wrote will
// open BEFORE handing it to the user. Never mutates and never stores anything.
app.post("/verify", (req, res) => {
  const { html = "" } = req.body || {};
  try {
    const problems = lintHtml(html);
    const errors = problems.filter((p) => p.severity === "error");
    res.json({
      status: errors.length ? "fail" : "ok",
      ok: errors.length === 0,
      errors: errors.map((p) => p.message),
      warnings: problems.filter((p) => p.severity === "warn").map((p) => p.message),
    });
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
