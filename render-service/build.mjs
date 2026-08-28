// Build the React Flow runtime that ships inside generated graph artifacts.
//
// This is a script rather than a line of esbuild CLI flags in package.json for
// one concrete reason: `--define:process.env.NODE_ENV="production"` does not
// survive npm's shell quoting identically on POSIX and Windows. When the quoting
// is lost the define silently does nothing, esbuild bundles React's DEVELOPMENT
// build, and the artifact dies in the browser with `process is not defined` —
// a failure that looks nothing like its cause.
import { build } from "esbuild";

const result = await build({
  entryPoints: ["flow-src/entry.js"],
  bundle: true,
  format: "iife",
  minify: true,
  target: ["es2019"],
  legalComments: "none",
  // Both spellings: React reads `process.env.NODE_ENV`, and some transitive
  // dependencies touch bare `process`.
  define: {
    "process.env.NODE_ENV": '"production"',
    process: '{"env":{"NODE_ENV":"production"}}',
  },
  outfile: "dist/weaveflow.js",
  metafile: true,
});

const out = result.metafile.outputs["dist/weaveflow.js"];
console.log(`weaveflow.js  ${(out.bytes / 1024).toFixed(1)}kb`);

// Guard the exact regression described above. A bundle that still references the
// development builds means the define did not apply, and the artifact would fail
// at runtime rather than here.
const { readFileSync } = await import("node:fs");
const src = readFileSync("dist/weaveflow.js", "utf-8");
if (/react-dom\.development|\breact\.development/.test(src)) {
  console.error("build failed: bundle contains React development builds (NODE_ENV define did not apply)");
  process.exit(1);
}
if (!src.includes("WeaveFlow")) {
  console.error("build failed: bundle does not assign window.WeaveFlow");
  process.exit(1);
}
