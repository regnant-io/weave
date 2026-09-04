// Single-file HTML artifacts: validate, repair, contain.
//
// The most useful thing the assistant can hand a student is often one complete
// HTML page — an interactive explainer, a revision sheet, a marking rubric, a
// small tool. Those pages are written wholesale by the model rather than from a
// spec, so this endpoint's job is not to render anything: it is to make sure the
// page the model wrote will actually OPEN.
//
// Three failure modes account for nearly everything that goes wrong:
//   1. ESM syntax in a classic <script>  -> instant SyntaxError, blank page
//   2. an external CDN / font / image    -> blocked by CSP, silently broken
//   3. a truncated file                  -> looks fine, ends mid-function
//
// (1) is repaired automatically where that is unambiguous. (2) and (3) are
// reported, because guessing at a fix would produce a page that renders but is
// not what was asked for.

import { checkSyntax, lintHtml, prepareScript } from "./js.js";

const MAX_BYTES = 900_000;

const CSP =
  "default-src 'none'; " +
  "script-src 'unsafe-inline' 'unsafe-eval' blob:; " +
  "worker-src blob:; " +
  "style-src 'unsafe-inline'; " +
  "img-src data: blob:; " +
  "media-src data: blob:; " +
  "font-src data:; " +
  "connect-src data: blob:; " +
  "form-action 'none'; " +
  "base-uri 'none'; " +
  "frame-src 'none'";

/** Rewrite every inline script that would fail to parse. */
function repairScripts(html) {
  const repairs = [];
  const failures = [];
  const out = html.replace(
    /<script\b([^>]*)>([\s\S]*?)<\/script>/gi,
    (match, attrs, body) => {
      if (/\bsrc\s*=/i.test(attrs)) return match;
      if (/type\s*=\s*["']?(application|text)\/(ld\+)?json/i.test(attrs)) return match;
      const isModule = /type\s*=\s*["']?module/i.test(attrs);
      if (!/^[ \t]*(import|export)[ \t{*]/m.test(body) && !(!isModule && /^[ \t]*await[ \t]/m.test(body))) {
        return match;
      }
      const prepared = prepareScript(body, { allowModule: true });
      if (!prepared.ok) {
        failures.push(prepared.error);
        return match;
      }
      repairs.push(...prepared.notes);
      if (prepared.scriptType === "module" && !isModule) {
        repairs.push("promoted a script to type=module for top-level await");
        return `<script type="module"${attrs}>${prepared.code}</script>`;
      }
      return `<script${attrs}>${prepared.code}</script>`;
    },
  );
  return { html: out, repairs, failures };
}

/**
 * Compile every inline script without running it.
 *
 * A truncated page -- the most common way a long generation goes wrong -- is
 * syntactically fine as HTML and catastrophic as JavaScript: the browser parses
 * the document, reaches an unterminated function, and abandons the whole script
 * silently. The page then loads to a blank body with a working stylesheet, which
 * looks far more like a rendering bug than like a file that stops mid-line.
 * Finding it here turns it into an error the model can act on.
 */
function checkScripts(html) {
  const problems = [];
  const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
  let m;
  let n = 0;
  while ((m = re.exec(html))) {
    n += 1;
    const attrs = m[1] || "";
    const body = m[2] || "";
    if (/\bsrc\s*=/i.test(attrs)) continue;
    if (/type\s*=\s*["']?(application|text)\/(ld\+)?json/i.test(attrs)) continue;
    if (!body.trim()) continue;
    const isModule = /type\s*=\s*["']?module/i.test(attrs);
    const res = checkSyntax(body, { async: isModule });
    if (!res.ok) {
      problems.push(
        `script #${n} does not parse: ${res.error}` +
          (res.line ? ` (around line ${res.line} of that script)` : "") +
          `. The browser abandons a script that fails to parse, so the page ` +
          `would load blank.`,
      );
    }
  }
  return problems;
}

/** Ensure the document carries the artifact CSP and a mobile viewport. */
function harden(html) {
  let out = html;
  if (!/Content-Security-Policy/i.test(out)) {
    const tag = `<meta http-equiv="Content-Security-Policy" content="${CSP}">`;
    out = /<head[^>]*>/i.test(out)
      ? out.replace(/<head[^>]*>/i, (m) => `${m}\n${tag}`)
      : `${tag}\n${out}`;
  }
  if (!/name\s*=\s*["']?viewport/i.test(out) && /<head[^>]*>/i.test(out)) {
    out = out.replace(
      /<head[^>]*>/i,
      (m) => `${m}\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">`,
    );
  }
  // Same reasoning as lib/custom.js: an uncaught error inside an opaque-origin
  // iframe is invisible to everyone, so the page reports on itself.
  if (!/weave-err/.test(out) && /<\/body>/i.test(out)) {
    out = out.replace(
      /<\/body>/i,
      `<div id="weave-err" style="display:none;position:fixed;left:0;right:0;bottom:0;z-index:99999;
margin:0;padding:10px 12px;border-top:2px solid #d4451d;background:#fff;color:#12110f;
font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:pre-wrap"></div>
<script>
window.addEventListener('error',function(e){var el=document.getElementById('weave-err');
if(el){el.style.display='block';el.textContent='Page error: '+(e.message||e.type)+(e.lineno?(' (line '+e.lineno+')'):'');}});
window.addEventListener('unhandledrejection',function(e){var el=document.getElementById('weave-err');
var r=e.reason;if(el){el.style.display='block';el.textContent='Page error (async): '+((r&&r.message)?r.message:String(r));}});
</script>
</body>`,
    );
  }
  return out;
}

/**
 * @param html  a complete HTML document written by the model
 * @param strict when true, `warn`-level lint findings also fail the request
 */
export function renderHtmlPage({ html = "", title = "Page", strict = false } = {}) {
  const src = String(html || "");
  if (!src.trim()) return { status: "error", error: "no html supplied" };
  if (src.length > MAX_BYTES) {
    return { status: "error", error: `html exceeds ${Math.round(MAX_BYTES / 1000)}KB` };
  }

  const fixed = repairScripts(src);
  if (fixed.failures.length) {
    return { status: "error", error: fixed.failures[0], repairs: fixed.repairs };
  }

  let doc = fixed.html;
  if (!/<html[\s>]/i.test(doc)) {
    // A body fragment is a reasonable thing to send; wrap it rather than
    // rejecting it, so the model does not have to remember the boilerplate.
    doc = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>${String(title).replace(/[<>&"]/g, "")}</title></head><body>\n${doc}\n</body></html>`;
  }
  doc = harden(doc);

  // Parse check before the lint. A script that does not compile is a harder
  // failure than anything the lint looks for, and reporting it first means the
  // model is told about the broken brace rather than about a missing viewport.
  const parseErrors = checkScripts(doc);
  if (parseErrors.length) {
    return { status: "error", error: parseErrors[0], problems: parseErrors,
             repairs: fixed.repairs };
  }

  const problems = lintHtml(doc);
  const errors = problems.filter((p) => p.severity === "error");
  const warnings = problems.filter((p) => p.severity === "warn");
  if (errors.length || (strict && warnings.length)) {
    return {
      status: "error",
      error: (errors[0] || warnings[0]).message,
      problems,
      repairs: fixed.repairs,
    };
  }

  return {
    status: "ok",
    html: doc,
    bytes: doc.length,
    repairs: fixed.repairs,
    warnings: warnings.map((w) => w.message),
  };
}
