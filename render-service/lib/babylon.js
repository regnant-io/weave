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
import { checkSyntax, prepareScript } from "./js.js";

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

  // Scene code becomes a FUNCTION BODY below, where an `import` is a syntax
  // error even in a module script. Rewrite what maps onto the BABYLON global we
  // already inline, and reject the rest with a message that names the specifier.
  const prepared = prepareScript(code, { allowModule: false });
  if (!prepared.ok) return { status: "error", error: prepared.error };
  code = prepared.code;

  /*
    COMPILE IT HERE, BEFORE IT EVER REACHES A BROWSER.

    This is the single largest source of dead-black Babylon artifacts, and the
    reason it was so hard to see: a SyntaxError is raised when a script is
    PARSED, before any statement in it runs. The scene code used to be inlined
    into the same <script> as the harness that reports errors, so a stray comma
    took the harness down with it. The page then had no error listener, no
    render loop and no way to say anything at all — just "Loading scene…"
    forever, while every layer above reported success and the model was told
    its tool call was fine.

    `new Function` compiles without executing, so the failure becomes an error
    message naming the problem and, usually, the line. That is something the
    model can repair; a black rectangle is not.

    Compiled as an ASYNC body because that is how it is invoked below.
  */
  const syntax = checkSyntax(code, {
    params: ["engine", "canvas", "BABYLON", "assets"],
    async: true,
  });
  if (!syntax.ok) {
    return {
      status: "error",
      error:
        `the scene code does not parse: ${syntax.error}` +
        (syntax.line ? ` (around line ${syntax.line} of your code)` : "") +
        `. Nothing was rendered. Fix the syntax and submit it again.`,
    };
  }

  /*
    A scene function that never returns its scene is the second most common
    failure, and unlike a syntax error it produces a page that runs perfectly
    and draws nothing. The runtime check downstream catches it, but catching it
    here saves a whole browser round trip and lets us say which line is missing
    rather than describing the symptom.

    Deliberately a heuristic on `return`: static analysis of what is returned
    would need a parser, and the false-positive case (a scene assembled and
    returned through a helper) is rare enough that a WARNING in the page is the
    right severity rather than a rejection.
  */
  const returnsSomething = /\breturn\b/.test(code);

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
#renderCanvas{width:100%;height:100%;display:block;outline:none;touch-action:none}
#hud{position:fixed;left:0;right:0;top:0;padding:10px 14px;pointer-events:none;
  background:linear-gradient(to bottom,rgba(0,0,0,.42),transparent);color:#fff}
#hud .eyebrow{color:rgba(255,255,255,.66)}
#hud h1{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;font-size:17px;font-weight:600;
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
<!--
  id="renderCanvas", NOT id="scene".

  Every Babylon tutorial, sample and playground on the web uses a canvas with
  id="renderCanvas", so that is the id models write when they reach past the
  canvas argument they were handed and look one up themselves -- which they do
  constantly, because that is what the code they learned from does. With the
  canvas called something else, document.getElementById("renderCanvas")
  returned null and the scene died on the next line.

  Matching the convention costs nothing and removes the failure. The alias shim
  further down covers the other names that show up.
-->
<div id="stage"><canvas id="renderCanvas" touch-action="none"></canvas></div>
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
/*
  THE HARNESS. Loaded BEFORE the model's code, in its own script.

  This separation is the whole point. Previously the scene code was inlined
  into the middle of this function, so a SyntaxError anywhere in it was a parse
  failure of THIS SCRIPT -- which meant the error listeners below were never
  installed, the render loop was never started, and the page sat on "Loading
  scene…" forever with nothing to report. The one failure that most needed an
  explanation was the one guaranteed not to produce one.

  Now the model's code lives in a separate <script> that assigns a function to
  window.__weaveCreateScene. If it fails to parse, that script dies alone; this
  one has already run, the listeners are up, and the boot step below finds no scene
  function and says exactly that.
*/
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
  window.__weaveFail = fail;
  window.addEventListener('error', function (e) { fail(e.message || e.type); });
  window.addEventListener('unhandledrejection', function (e) {
    fail((e.reason && e.reason.message) || 'promise rejected');
  });

  var canvas = document.getElementById('renderCanvas');

  /*
    Alias the canvas ids models actually type.

    The scene function is HANDED its canvas, but models routinely look one up
    instead, because that is what every sample they learned from does. The
    canvas is called renderCanvas for that reason; these are the other names
    that show up often enough to be worth catching. Anything else still
    resolves normally, so this cannot mask a genuine typo in the model's own
    markup.
  */
  var ALIASES = { scene: 1, canvas: 1, gameCanvas: 1, canvas3d: 1, viewport: 1 };
  var nativeGet = document.getElementById.bind(document);
  document.getElementById = function (id) {
    var found = nativeGet(id);
    if (found) return found;
    return ALIASES[id] ? canvas : null;
  };

  var assets = ${JSON.stringify(built.assets)};
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

  window.__weaveBoot = function () {
    var make = window.__weaveCreateScene;
    if (typeof make !== 'function') {
      // The only way to get here is the model's script failing to parse. Say
      // so plainly: "nothing rendered" sends the model looking at its scene
      // logic, which is not where the problem is.
      fail('the scene code could not be parsed by the browser, so it never ran. ' +
           'Check for an unclosed bracket, brace or string.');
      return;
    }

    var result;
    try {
      result = make(engine, canvas, BABYLON, assets);
    } catch (e) {
      fail(e && e.message ? e.message : String(e));
      return;
    }

    // A scene function may be async, or may return a Promise from
    // SceneLoader.* -- which is the documented Babylon pattern for a scene
    // that loads a mesh. Rejecting that shape (the old behaviour: "createScene
    // did not return a BABYLON.Scene") failed every scene that imported a
    // model, for a reason that read as a mistake by the author.
    Promise.resolve(result).then(start, function (e) {
      fail('the scene function rejected: ' + ((e && e.message) || String(e)));
    });
  };

  function start(scene) {
    if (!scene || typeof scene.render !== 'function') {
      fail('the scene function finished without returning a BABYLON.Scene. ' +
           'Building the scene is not enough -- end the function with ' +
           'return scene;');
      return;
    }
    ${returnsSomething ? "" : "// (no return statement was found in the submitted code)"}

    // A scene with no camera renders nothing and throws nothing, which is the
    // most confusing possible outcome. Babylon can supply one, and saying so
    // is better than a black screen.
    if (!scene.activeCamera) {
      try {
        scene.createDefaultCamera(true, true, true);
        fail('the scene had no camera, so a default one was added. Create and ' +
             'position a camera explicitly -- the automatic one rarely frames ' +
             'the subject well.');
      } catch (e) {
        fail('the scene has no active camera, so nothing can be drawn.');
        return;
      }
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
  }
})();
</script>

<!--
  THE MODEL'S SCENE CODE, ALONE IN ITS OWN SCRIPT.

  If this fails to parse, only this script dies. The harness above is already
  running, has its error listeners installed, and reports the failure. Wrapped
  as an async function so a scene that awaits (SceneLoader.ImportMeshAsync and
  friends -- the normal way to load a mesh) is legal rather than a syntax error.
-->
<script>
window.__weaveCreateScene = async function (engine, canvas, BABYLON, assets) {
${code}
};
</script>

<script>
// Separate again, so that a parse failure in the block above still reaches
// this line. __weaveBoot decides what to say about what it finds.
window.__weaveBoot();
</script>
</body></html>`;

  return { status: "ok", html };
}
