// Babylon.js scenes: games, 3D builders, physics toys, walkthroughs.
//
// WHY THIS EXISTS ALONGSIDE /three
// -------------------------------
// `three3d.js` is spec-driven: the caller passes DATA (points, edges, a grid)
// and this service owns every line of rendering code. That is the right shape
// for a 3D *chart*, and it stays.
//
// It is the wrong shape for a game. There is no schema for "a first-person
// walkthrough of a building the student designed", and inventing one would only
// ever cover what we thought of first. So this path takes model-authored scene
// code and contains it, exactly like lib/custom.js does — see that file for why
// containment rather than code review is the control that makes this safe:
// artifacts render in an opaque-origin iframe (`sandbox="allow-scripts"` with no
// `allow-same-origin`) under a `default-src 'none'` CSP, so the page has no
// route to cookies, storage, the parent document, or the network.
//
// The model writes the body of a `createScene(engine, canvas, BABYLON, assets)`
// function and returns a BABYLON.Scene. Everything around it — engine setup,
// resize handling, the render loop, error surfacing, a loading state, pointer
// lock hygiene — is ours, because those are the parts that are always the same
// and always subtly wrong when regenerated from scratch.

import { esc, baseCss } from "./theme.js";
import { screenCode } from "./custom.js";

const MAX_CODE_BYTES = 400_000;
//: Inlined binary assets (.glb, textures, audio) as data URLs. Kept modest: the
//: whole artifact is one HTML file held in object storage and loaded into an
//: iframe, so a 50MB scene would simply never open.
const MAX_ASSET_BYTES = 24 * 1024 * 1024;

/**
 * Normalise the caller's asset map into inlinable data URLs.
 *
 * Scene code cannot fetch anything (there is no network inside the artifact),
 * so any mesh, texture or sound it needs has to travel with it. The backend
 * reads those bytes out of the project workspace and passes them here.
 */
function buildAssets(assets) {
  const out = {};
  let total = 0;
  for (const [name, value] of Object.entries(assets || {})) {
    if (typeof value !== "string" || !value) continue;
    const url = value.startsWith("data:") ? value : `data:application/octet-stream;base64,${value}`;
    total += url.length;
    if (total > MAX_ASSET_BYTES) {
      return { error: `inlined assets exceed ${Math.round(MAX_ASSET_BYTES / 1024 / 1024)}MB` };
    }
    out[String(name)] = url;
  }
  return { assets: out };
}

export function renderBabylon({
  code = "",
  title = "3D scene",
  subtitle = "",
  theme = "dark",
  assets = {},
  babylonSrc = "",
  loadersSrc = "",
  guiSrc = "",
  physics = false,
  controls = "",
}) {
  if (!String(code).trim()) return { status: "error", error: "no scene code supplied" };
  if (code.length > MAX_CODE_BYTES) {
    return { status: "error", error: `scene code exceeds ${MAX_CODE_BYTES} bytes` };
  }
  if (!babylonSrc) {
    return {
      status: "error",
      error: "Babylon.js is not bundled in this render service (run npm install in render-service)",
    };
  }

  const violations = screenCode(code);
  if (violations.length) {
    return {
      status: "error",
      error:
        `scene code uses capabilities the visual sandbox forbids: ${violations.join(", ")}. ` +
        `Scenes are fully offline — pass meshes and textures via \`assets\` (they are ` +
        `inlined as data URLs and exposed as the \`assets\` argument) instead of loading them.`,
    };
  }

  const built = buildAssets(assets);
  if (built.error) return { status: "error", error: built.error };

  const csp =
    "default-src 'none'; " +
    "script-src 'unsafe-inline' 'unsafe-eval' blob:; " + // Babylon compiles shaders and uses workers
    "worker-src blob:; " +
    "style-src 'unsafe-inline'; " +
    "img-src data: blob:; " +
    "media-src data: blob:; " +
    "font-src data:; " +
    "connect-src data: blob:; " +   // data-URL asset loads go through XHR inside Babylon
    "form-action 'none'; base-uri 'none'; frame-src 'none'";

  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>${esc(title)}</title>
<style>${baseCss(theme)}
html,body{height:100%;margin:0;overflow:hidden;background:var(--bg)}
#stage{position:fixed;inset:0}
#scene{width:100%;height:100%;display:block;outline:none;touch-action:none}
#hud{position:fixed;left:0;right:0;top:0;padding:10px 14px;pointer-events:none;
  background:linear-gradient(to bottom,rgba(0,0,0,.42),transparent);color:#fff}
#hud .eyebrow{color:rgba(255,255,255,.66)}
#hud h1{font-family:Georgia,"Times New Roman",serif;font-size:17px;font-weight:600;
  margin:1px 0 0;letter-spacing:-.01em;text-shadow:0 1px 3px rgba(0,0,0,.5)}
#hud p{margin:2px 0 0;font-size:12px;opacity:.8;max-width:60ch}
#hints{position:fixed;left:14px;bottom:12px;font-size:11.5px;color:#fff;opacity:.62;
  pointer-events:none;text-shadow:0 1px 3px rgba(0,0,0,.6);white-space:pre-line}
#fps{position:fixed;right:14px;bottom:12px;font-family:ui-monospace,Consolas,monospace;
  font-size:11px;color:#fff;opacity:.45;pointer-events:none}
#boot{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;
  background:var(--bg);color:var(--fg-muted);font-size:13px;transition:opacity .45s ease;z-index:5}
#boot.gone{opacity:0;pointer-events:none}
#err{position:fixed;left:0;right:0;bottom:0;display:none;z-index:9;
  padding:12px 14px;background:var(--surface-2);border-top:2px solid var(--accent);
  font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:pre-wrap;
  max-height:45%;overflow:auto;color:var(--fg)}
</style></head>
<body>
<div id="stage"><canvas id="scene" touch-action="none"></canvas></div>
${title || subtitle ? `<div id="hud"><div class="eyebrow">Weave</div>
${title ? `<h1>${esc(title)}</h1>` : ""}${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div>` : ""}
${controls ? `<div id="hints">${esc(controls)}</div>` : ""}
<div id="fps"></div>
<div id="boot">Loading scene…</div>
<div id="err"></div>

<script>${babylonSrc}</script>
${loadersSrc ? `<script>${loadersSrc}</script>` : ""}
${guiSrc ? `<script>${guiSrc}</script>` : ""}

<script>
(function () {
  var errEl = document.getElementById('err');
  function fail(msg) {
    // A thrown error inside an opaque-origin iframe is invisible to the user AND
    // to the model that wrote the scene; without this the artifact is just black.
    if (!errEl) return;
    errEl.style.display = 'block';
    errEl.textContent = 'Scene error: ' + msg;
    var boot = document.getElementById('boot');
    if (boot) boot.classList.add('gone');
  }
  window.addEventListener('error', function (e) { fail(e.message || e.type); });
  window.addEventListener('unhandledrejection', function (e) {
    fail((e.reason && e.reason.message) || 'promise rejected');
  });

  var assets = ${JSON.stringify(built.assets)};
  var canvas = document.getElementById('scene');
  var engine;
  try {
    engine = new BABYLON.Engine(canvas, true, {
      preserveDrawingBuffer: true,
      stencil: true,
      // Old iPads and cheap Androids are a real part of this audience; a scene
      // that silently fails to start there is worse than one that runs at 30fps.
      failIfMajorPerformanceCaveat: false,
    }, true);
  } catch (e) {
    fail('WebGL is unavailable on this device (' + (e.message || e) + ')');
    return;
  }

  ${physics ? "try { if (BABYLON.CannonJSPlugin && window.CANNON) { /* physics plugin available */ } } catch (e) {}" : ""}

  function createScene(engine, canvas, BABYLON, assets) {
${code}
  }

  var scene;
  try {
    scene = createScene(engine, canvas, BABYLON, assets);
  } catch (e) {
    fail(e && e.message ? e.message : String(e));
    return;
  }
  if (!scene || typeof scene.render !== 'function') {
    fail('createScene did not return a BABYLON.Scene');
    return;
  }

  var fpsEl = document.getElementById('fps');
  var frames = 0;
  var booted = false;

  engine.runRenderLoop(function () {
    try {
      scene.render();
      if (!booted && ++frames > 2) {
        booted = true;
        var boot = document.getElementById('boot');
        if (boot) boot.classList.add('gone');
      }
      if (fpsEl && (frames & 31) === 0) fpsEl.textContent = engine.getFps().toFixed(0) + ' fps';
    } catch (e) {
      // Stop the loop on the FIRST render failure. Left running it would repeat
      // the same exception 60 times a second and lock the tab.
      engine.stopRenderLoop();
      fail(e && e.message ? e.message : String(e));
    }
  });

  window.addEventListener('resize', function () { engine.resize(); });
  // The iframe is resized by the panel, which does not always fire a window
  // resize event; observing the element itself is what keeps the canvas correct.
  if (window.ResizeObserver) {
    try { new ResizeObserver(function () { engine.resize(); }).observe(canvas); } catch (e) {}
  }
  // Never leave the page holding pointer lock — the user cannot get their cursor
  // back without knowing to press Escape.
  window.addEventListener('blur', function () {
    if (document.exitPointerLock) { try { document.exitPointerLock(); } catch (e) {} }
  });
})();
</script>
</body></html>`;

  return { status: "ok", html };
}
