// Making model-authored JavaScript actually run inside an artifact.
//
// WHY THIS EXISTS
// ---------------
// Artifacts are single self-contained pages with no network and no module
// resolver. Models, trained on ordinary web projects, routinely open their code
// with `import * as THREE from "three"`. Dropped into a classic <script> that is
// an immediate, fatal:
//
//     Uncaught SyntaxError: Cannot use import statement outside a module
//
// and the visual renders blank. The old behaviour was to inline the code
// verbatim and let the browser reject it, which produced a broken artifact the
// model had no way of knowing was broken.
//
// So: rewrite what can be rewritten, force module scope when the code genuinely
// needs it, and fail LOUDLY AND SPECIFICALLY when neither is possible — an error
// that names the offending import is one the model can act on; a blank page is
// not.

/**
 * Bare specifiers whose library this service already inlines as a global. An
 * import of one of these is a naming convention, not a dependency, so it can be
 * rewritten to a local binding.
 */
const GLOBALS = {
  three: "THREE",
  "three.js": "THREE",
  threejs: "THREE",
  babylonjs: "BABYLON",
  "babylon.js": "BABYLON",
  "@babylonjs/core": "BABYLON",
  "@babylonjs/gui": "BABYLON.GUI",
  "@babylonjs/loaders": "BABYLON",
  react: "React",
  "react-dom": "ReactDOM",
  "react-dom/client": "ReactDOM",
  reactflow: "ReactFlow",
  d3: "d3",
  dagre: "dagre",
};

/** `import ... from "x"` / `import "x"` — one statement, at any indentation. */
const IMPORT_RE =
  /^[ \t]*import[ \t]+(?:([\s\S]*?)[ \t]+from[ \t]*)?["']([^"']+)["'][ \t]*;?[ \t]*$/gm;

/** `export default x` / `export { a, b }` / `export const x` — the keyword only. */
const EXPORT_DEFAULT_RE = /^[ \t]*export[ \t]+default[ \t]+/gm;
const EXPORT_NAMED_RE = /^[ \t]*export[ \t]*\{[^}]*\}[ \t]*;?[ \t]*$/gm;
const EXPORT_DECL_RE = /^([ \t]*)export[ \t]+(?=(?:const|let|var|function|class|async)\b)/gm;

/** Top-level `await` forces real module scope; nothing else can provide it. */
const TOP_LEVEL_AWAIT_RE = /^[ \t]*(?:await[ \t]|(?:const|let|var)\s+[\w{}[\],\s]+=\s*await\s)/m;

/**
 * Turn one import clause into equivalent bindings against an existing global.
 *
 * Handles the three shapes that actually occur:
 *   import * as NS from "x"     -> const NS = GLOBAL;
 *   import D from "x"           -> const D = GLOBAL;
 *   import { a, b as c } from "x" -> const { a, b: c } = GLOBAL;
 * and the mixed `import D, { a } from "x"`.
 */
function bindingsFor(clause, globalName) {
  const out = [];
  let rest = String(clause || "").trim();

  const ns = rest.match(/\*\s+as\s+([A-Za-z_$][\w$]*)/);
  if (ns) {
    out.push(`const ${ns[1]} = ${globalName};`);
    rest = rest.replace(ns[0], "").replace(/^\s*,\s*/, "").trim();
  }

  const named = rest.match(/\{([^}]*)\}/);
  let namedSrc = "";
  if (named) {
    namedSrc = named[1];
    rest = rest.replace(named[0], "").replace(/\s*,\s*$/, "").replace(/^\s*,\s*/, "").trim();
  }

  const def = rest.match(/^([A-Za-z_$][\w$]*)/);
  if (def) {
    // A default import of a UMD global is the namespace itself — that is what
    // `export default` compiles to in every bundle we inline.
    out.push(`const ${def[1]} = ${globalName}.default || ${globalName};`);
  }

  if (namedSrc.trim()) {
    const parts = namedSrc
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => {
        const as = s.match(/^([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)$/);
        return as ? `${as[1]}: ${as[2]}` : s;
      });
    if (parts.length) out.push(`const { ${parts.join(", ")} } = ${globalName};`);
  }

  return out.join("\n");
}

/**
 * Prepare model-authored JS for inlining.
 *
 * @returns {{ ok: boolean, code: string, scriptType: "classic"|"module",
 *             notes: string[], error?: string }}
 */
export function prepareScript(rawCode, { allowModule = true } = {}) {
  const notes = [];
  let code = String(rawCode || "");
  if (!code.trim()) return { ok: true, code: "", scriptType: "classic", notes };

  const unresolved = [];
  code = code.replace(IMPORT_RE, (match, clause, spec) => {
    const key = String(spec).toLowerCase();
    // A relative import can never resolve — there is no second file to fetch.
    if (key.startsWith(".") || key.startsWith("/")) {
      unresolved.push(spec);
      return "";
    }
    const globalName = GLOBALS[key] || GLOBALS[key.split("/")[0]];
    if (!globalName) {
      unresolved.push(spec);
      return "";
    }
    if (!clause) {
      // A side-effect-only import of an already-inlined library is a no-op.
      notes.push(`dropped side-effect import of "${spec}" (already inlined)`);
      return "";
    }
    notes.push(`rewrote import of "${spec}" to the inlined ${globalName} global`);
    return bindingsFor(clause, globalName);
  });

  if (unresolved.length) {
    const list = [...new Set(unresolved)].map((s) => `"${s}"`).join(", ");
    return {
      ok: false,
      code: "",
      scriptType: "classic",
      notes,
      error:
        `this artifact imports ${list}, which cannot be resolved: a rendered visual is ` +
        `a single self-contained page with no bundler, no module resolver and no network. ` +
        `Write plain browser JavaScript with no import statements. Libraries this service ` +
        `already inlines are available as globals (THREE, BABYLON, React, ReactFlow, dagre) ` +
        `— use them directly. Everything else must be written inline.`,
    };
  }

  // `export` is meaningless in a page nothing imports; strip it rather than
  // forcing module scope for a keyword that does nothing here.
  const hadExport =
    EXPORT_DEFAULT_RE.test(code) || EXPORT_NAMED_RE.test(code) || EXPORT_DECL_RE.test(code);
  EXPORT_DEFAULT_RE.lastIndex = 0;
  EXPORT_NAMED_RE.lastIndex = 0;
  EXPORT_DECL_RE.lastIndex = 0;
  if (hadExport) {
    code = code
      .replace(EXPORT_NAMED_RE, "")
      .replace(EXPORT_DEFAULT_RE, "")
      .replace(EXPORT_DECL_RE, "$1");
    notes.push("removed export statements (an artifact is never imported)");
  }

  let scriptType = "classic";
  if (allowModule && TOP_LEVEL_AWAIT_RE.test(code)) {
    scriptType = "module";
    notes.push("used <script type=module> because the code awaits at top level");
  }

  return { ok: true, code, scriptType, notes };
}

/**
 * Static sanity checks on a finished HTML page.
 *
 * Catches the failures that make an artifact look fine to whoever generated it
 * and blank to whoever opens it. Cheap, conservative, and never a hard gate on
 * its own — findings are returned with a severity so the caller decides.
 */
export function lintHtml(html) {
  const problems = [];
  const src = String(html || "");
  const add = (severity, message) => problems.push({ severity, message });

  if (!src.trim()) {
    add("error", "document is empty");
    return problems;
  }
  if (!/<html[\s>]/i.test(src)) add("warn", "no <html> element");
  if (!/<\/body>/i.test(src)) add("warn", "no closing </body> — the document may be truncated");

  // The bug this whole module exists to prevent: ESM syntax inside a classic
  // script. Check every script block, honouring its own type attribute.
  const scriptRe = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
  let m;
  let idx = 0;
  while ((m = scriptRe.exec(src))) {
    idx += 1;
    const attrs = m[1] || "";
    const body = m[2] || "";
    if (/\bsrc\s*=/i.test(attrs)) {
      // ANY src is wrong here, not just an http one.
      //
      // An artifact is a single file with no origin and no network, so
      // `<script src="babylon.js">` fails exactly as completely as
      // `<script src="https://cdn...">` — it just fails silently, leaving a
      // blank page and no console error worth the name. Only a data: URI can
      // actually resolve.
      if (/src\s*=\s*["']?data:/i.test(attrs)) {
        continue;
      }
      if (/src\s*=\s*["']?https?:|src\s*=\s*["']?\/\//i.test(attrs)) {
        add("error", `script #${idx} loads an external URL; artifacts have no network`);
      } else {
        add(
          "error",
          `script #${idx} loads a separate file; an artifact is ONE self-contained ` +
            `document with no origin to resolve it against. Paste the code inline.`,
        );
      }
      continue;
    }
    const isModule = /type\s*=\s*["']?module/i.test(attrs);
    const isJson = /type\s*=\s*["']?(application|text)\/(ld\+)?json/i.test(attrs);
    if (isJson) continue;
    if (!isModule && /^[ \t]*(import|export)[ \t{*]/m.test(body)) {
      add(
        "error",
        `script #${idx} uses import/export inside a classic <script> — this throws ` +
          `"Cannot use import statement outside a module" and the page renders blank`,
      );
    }
    if (!isModule && /^[ \t]*await[ \t]/m.test(body)) {
      add("error", `script #${idx} awaits at top level inside a classic <script>`);
    }
  }

  if (/\bfetch\s*\(|XMLHttpRequest|new\s+WebSocket/i.test(src)) {
    add("warn", "page attempts a network request; artifacts run fully offline");
  }
  if (/<img[^>]+src\s*=\s*["']?https?:/i.test(src)) {
    add("error", "image loads from an external URL; inline it as a data: URI");
  }
  if (/@import\s+url|<link[^>]+href\s*=\s*["']?https?:/i.test(src)) {
    add("error", "stylesheet or font loads from an external URL; inline it");
  }

  // Truncation is the other silent killer: a file cut mid-function looks
  // complete until it is opened.
  const opens = (src.match(/\{/g) || []).length;
  const closes = (src.match(/\}/g) || []).length;
  if (opens - closes > 2) {
    add("warn", `${opens - closes} more { than } — the file may be truncated`);
  }
  if (/\b(\.\.\.|\/\* *rest (of|unchanged)|TODO: *(fill|implement)|<!-- *rest)/i.test(src)) {
    add("warn", "contains an ellipsis or 'rest unchanged' marker — content may be abbreviated");
  }

  return problems;
}

/**
 * Compile model-authored code WITHOUT running it, to find syntax errors here
 * rather than in the user's browser.
 *
 * WHY THIS IS WORTH A SEPARATE PASS
 *
 * A syntax error is not like a runtime error. A runtime error is thrown from
 * inside a script that has already parsed, so an installed `window.onerror`
 * handler catches it and the artifact can say what went wrong. A SyntaxError
 * happens at PARSE time, before a single statement in that script executes —
 * so if the error-reporting harness lives in the same <script> as the model's
 * code, the harness never runs either. The result is the failure that is
 * hardest to act on: a completely blank page, no console output worth the
 * name, and a tool result that said "ok".
 *
 * `new Function` compiles its body and throws on a syntax error without
 * executing anything, which is exactly the check needed and costs microseconds.
 * It is not a sandbox escape: nothing is called.
 *
 * @param {string} code    the source to compile
 * @param {object} opts
 * @param {string[]} opts.params  parameter names, when the code is a function body
 * @param {boolean} opts.async    compile as an async function body
 * @returns {{ ok: boolean, error?: string, line?: number }}
 */
export function checkSyntax(code, { params = [], async = false } = {}) {
  const src = String(code || "");
  if (!src.trim()) return { ok: true };
  try {
    if (async) {
      // There is no AsyncFunction constructor in scope by default; get it from
      // an async function's own constructor.
      const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
      new AsyncFunction(...params, src);
    } else {
      new Function(...params, src);
    }
    return { ok: true };
  } catch (e) {
    const message = String((e && e.message) || e);
    // V8 puts the offending line in the stack for compile errors; pull the
    // line number out when it is there, because "line 214" turns an
    // unactionable message into a pointer.
    let line;
    const m = /<anonymous>:(\d+):(\d+)/.exec(String((e && e.stack) || ""));
    if (m) line = Number(m[1]) - 2; // the wrapper contributes two lines
    return { ok: false, error: message, line: line && line > 0 ? line : undefined };
  }
}

/**
 * Whether an SVG string actually draws anything.
 *
 * The failure this exists for: a chart or diagram that renders to a
 * syntactically perfect `<svg>` element containing nothing but a background
 * rectangle, or nothing at all. Every layer reports success — the spec
 * compiled, the view rendered, the file was written, the tool returned "ok" —
 * and the user is shown an empty box. Nothing in the pipeline was ever asked
 * the only question that matters, which is whether there is ink on the page.
 *
 * Counted as ink: any path, shape, text, image or use element with actual
 * geometry. Deliberately NOT counted: the root element, `<defs>` and its
 * contents (gradients and markers are definitions, not marks), `<style>`,
 * `<title>`/`<desc>`, and a single full-bleed background `<rect>`, which every
 * renderer emits whether or not it drew anything on top of it.
 */
export function svgHasContent(svg) {
  const src = String(svg || "");
  if (!src.trim()) return false;

  // Strip the parts that are definitions rather than marks, so a spec whose
  // only output is a gradient definition is correctly seen as empty.
  const body = src
    .replace(/<defs[\s\S]*?<\/defs>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<title[\s\S]*?<\/title>/gi, "")
    .replace(/<desc[\s\S]*?<\/desc>/gi, "")
    .replace(/<!--[\s\S]*?-->/g, "");

  // Text counts only when it has a non-empty body: an axis renders empty
  // <text> elements for absent labels.
  if (/<text[^>]*>\s*[^<\s][\s\S]*?<\/text>/i.test(body)) return true;
  if (/<(image|use|foreignObject)\b/i.test(body)) return true;
  if (/<path[^>]*\sd\s*=\s*["'][^"']*[\d.]/i.test(body)) return true;
  if (/<(circle|ellipse|line|polyline|polygon)\b/i.test(body)) return true;

  // Rects last, and only past the first one: renderers emit exactly one
  // full-bleed background rect for an otherwise empty chart.
  const rects = body.match(/<rect\b/gi);
  if (rects && rects.length > 1) return true;

  return false;
}
