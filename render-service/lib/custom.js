// The escape hatch: model-authored code, executed under hard containment.
//
// Spec-driven rendering covers the common cases well, but it caps what the AI
// can invent — and "generate a visualisation nobody has written a schema for
// yet" is a real requirement. This path accepts raw JS/HTML from the model.
//
// That is only acceptable because of where the output lands. Artifacts are
// served from the artifact endpoint and displayed in an iframe with
// `sandbox="allow-scripts"` and NO `allow-same-origin`, which puts the page in
// an opaque origin: it cannot read cookies, cannot touch localStorage, cannot
// reach the parent document, and cannot make same-origin requests. On top of
// that the page carries its own restrictive CSP, so it cannot load or contact
// anything off-box even if the iframe attributes were ever loosened.
//
// The threat model here is a confused or prompt-injected model emitting code
// that tries to exfiltrate the user's session — not a determined attacker who
// already controls the model weights. Containment, not code review, is the
// control that makes this safe.

import { esc, baseCss } from "./theme.js";
import { prepareScript } from "./js.js";

/** Patterns that indicate the page is trying to leave its box. */
const FORBIDDEN = [
  [/\bfetch\s*\(/i, "fetch()"],
  [/XMLHttpRequest/i, "XMLHttpRequest"],
  [/\bWebSocket\b/i, "WebSocket"],
  [/\bEventSource\b/i, "EventSource"],
  [/\bnavigator\s*\.\s*sendBeacon/i, "sendBeacon"],
  [/\bimport\s*\(/i, "dynamic import()"],
  [/\bparent\s*\./i, "parent access"],
  [/\btop\s*\./i, "top access"],
  [/\bwindow\s*\.\s*opener/i, "window.opener"],
  [/\bdocument\s*\.\s*cookie/i, "document.cookie"],
  [/\blocalStorage\b/i, "localStorage"],
  [/\bsessionStorage\b/i, "sessionStorage"],
  [/\bindexedDB\b/i, "indexedDB"],
  [/<\s*iframe/i, "nested iframe"],
  [/\bsrc\s*=\s*["']?https?:/i, "external resource"],
  [/@import\s+url/i, "external stylesheet"],
];

/**
 * Reject code that is obviously reaching outside the sandbox.
 *
 * This is defence in depth, NOT the security boundary — a regex scan of
 * JavaScript is trivially evadable and must never be treated as sufficient.
 * The CSP and the opaque-origin iframe are what actually contain the page.
 * This check exists to turn an honest mistake into a clear error message
 * instead of a silently broken visual.
 */
export function screenCode(code) {
  const found = [];
  for (const [re, name] of FORBIDDEN) if (re.test(code)) found.push(name);
  return found;
}

export function renderCustom({
  code = "",
  html = "",
  title = "Visual",
  theme = "light",
  libs = [],
  threeSrc = "",
}) {
  const source = `${html}\n${code}`;
  if (!source.trim()) return { status: "error", error: "no code supplied" };
  if (source.length > 400_000) return { status: "error", error: "code exceeds 400KB" };

  // Resolve ESM syntax BEFORE anything else. A model that opens with
  // `import * as THREE from "three"` used to get a page that parsed as far as
  // the first line and then died; now the import either becomes a binding
  // against the global we already inline, or the caller gets an error that says
  // exactly which specifier is the problem.
  const prepared = prepareScript(code);
  if (!prepared.ok) return { status: "error", error: prepared.error };
  code = prepared.code;

  const violations = screenCode(source);
  if (violations.length) {
    return {
      status: "error",
      error:
        `generated code uses capabilities the visual sandbox forbids: ${violations.join(", ")}. ` +
        `Rendered visuals are fully offline — inline all data and draw with canvas/SVG/WebGL only.`,
    };
  }

  const wantsThree = libs.includes("three") || /\bTHREE\b/.test(source);
  if (wantsThree && !threeSrc) {
    return { status: "error", error: "three.js requested but not bundled in the render service" };
  }

  // `script-src 'unsafe-inline'` is required because the model's code IS inline;
  // everything else is denied outright, so the page has no route off the box.
  const csp =
    "default-src 'none'; " +
    "script-src 'unsafe-inline'; " +
    "style-src 'unsafe-inline'; " +
    "img-src data: blob:; " +
    "font-src data:; " +
    "connect-src 'none'; " +
    "form-action 'none'; " +
    "base-uri 'none'; " +
    "frame-src 'none'";

  return {
    status: "ok",
    html: `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<style>${baseCss(theme)}
html,body{height:100%}
.wrap{padding:16px}
canvas{max-width:100%}
#weave-err{display:none;margin:12px 0;padding:10px 12px;border-left:2px solid var(--accent);
  background:var(--surface-2);font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap}
</style></head>
<body>
<div id="weave-err"></div>
${html || '<div class="wrap"><div id="root"></div></div>'}
${wantsThree ? `<script>${threeSrc}</script>` : ""}
<script>
// Surface runtime errors in the artifact itself. Without this a thrown error
// inside an opaque-origin iframe is invisible to both the user and the model,
// and the visual just silently renders blank.
//
// This also has to catch the PARSE error of the block below, which a try/catch
// around the code physically cannot: a SyntaxError happens before any statement
// in that script runs. That is why the model's code is no longer wrapped in a
// try - the wrapper never caught the error people actually hit, and it put every
// top-level const declaration in a block scope where inline handlers could not
// reach it.
window.addEventListener('error', function(e){
  var el=document.getElementById('weave-err');
  if(el){ el.style.display='block';
    el.textContent='Visual error: '+(e.message||e.type)+(e.lineno?(' (line '+e.lineno+')'):''); }
});
window.addEventListener('unhandledrejection', function(e){
  var el=document.getElementById('weave-err');
  var r=e.reason;
  if(el){ el.style.display='block';
    el.textContent='Visual error (async): '+((r&&r.message)?r.message:String(r)); }
});
</script>
<script${prepared.scriptType === "module" ? ' type="module"' : ""}>
${code}
</script>
</body></html>`,
    notes: prepared.notes,
  };
}
