import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { app } from "../server.js";

let server;
let base;

before(async () => {
  server = app.listen(0, "127.0.0.1");
  await new Promise((resolve, reject) => {
    server.once("listening", resolve);
    server.once("error", reject);
  });
  base = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  if (server) await new Promise((resolve) => server.close(resolve));
});

test("health reports the bundles used by generated artifacts", async () => {
  const response = await fetch(`${base}/health`);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.status, "ok");
  assert.equal(body.engines.vega, true);
  assert.equal(body.engines.babylon, true);
  assert.equal(body.engines.flow, true);
  assert.ok(body.limits.max_concurrent >= 1);
});

test("complexity guard rejects oversized data arrays before rendering", async () => {
  const response = await fetch(`${base}/diagram`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ spec: { nodes: Array.from({ length: 10001 }, (_, i) => i) } }),
  });
  assert.equal(response.status, 413);
  assert.equal((await response.json()).code, "complexity_limit");
});

test("Vega-Lite 6 renders a non-empty chart through the backend contract", async () => {
  const response = await fetch(`${base}/chart`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      format: "json",
      spec: {
        $schema: "https://vega.github.io/schema/vega-lite/v6.json",
        mark: "bar",
        data: { values: [{ region: "Dodoma", value: 4 }, { region: "Mwanza", value: 7 }] },
        encoding: {
          x: { field: "region", type: "nominal" },
          y: { field: "value", type: "quantitative" },
        },
      },
    }),
  });
  const payload = await response.text();
  assert.equal(response.status, 200, payload);
  const body = JSON.parse(payload);
  assert.match(body.svg, /<svg\b/);
  assert.match(body.svg, /role="graphics-symbol"/);
});

test("static verification rejects pages that depend on remote scripts", async () => {
  const response = await fetch(`${base}/verify`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      html: '<!doctype html><script src="https://example.com/app.js"></script>',
    }),
  });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.ok, false);
  assert.ok(body.errors.some((message) => /external|network|script/i.test(message)));
});

async function postJson(path, body) {
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.text();
  assert.equal(response.status, 200, `${path}: ${payload.slice(0, 500)}`);
  return { response, payload, body: JSON.parse(payload) };
}

test("spec renderers return self-contained HTML through their API contracts", async () => {
  const cases = [
    ["/diagram", {
      spec: {
        kind: "flow",
        nodes: [{ id: "question", label: "Question" }, { id: "answer", label: "Answer" }],
        edges: [{ from: "question", to: "answer" }],
      },
    }],
    ["/simulation", {
      spec: { mode: "plot", x: { name: "x", min: 0, max: 5 }, curves: [{ label: "square", y: "x*x" }] },
    }],
    ["/animation", {
      spec: { steps: [{ kind: "line", points: [[10, 10], [120, 80]], caption: "Connect" }] },
    }],
    ["/graph", {
      spec: {
        nodes: [{ id: "a", label: "A" }, { id: "b", label: "B" }],
        edges: [{ source: "a", target: "b" }],
      },
    }],
  ];

  for (const [path, request] of cases) {
    const result = await postJson(path, request);
    assert.equal(result.body.status, "ok", path);
    assert.match(result.body.html, /<!doctype html>/i, path);
    assert.doesNotMatch(result.body.html, /<script\b[^>]*\bsrc\s*=/i, path);
  }
});

test("deck endpoint returns a complete HTML document", async () => {
  const response = await fetch(`${base}/deck`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ slides: [{ title: "Audit", body: "Verified output" }] }),
  });
  const payload = await response.text();
  assert.equal(response.status, 200, payload.slice(0, 500));
  assert.match(response.headers.get("content-type"), /text\/html/);
  assert.match(payload, /<!doctype html>/i);
  assert.doesNotMatch(payload, /<script\b[^>]*\bsrc\s*=/i);
});

test("HTML endpoint preserves a valid complete page", async () => {
  const result = await postJson("/html", {
    title: "Contract page",
    html: "<!doctype html><html><head><title>Contract</title></head><body><main>Ready</main></body></html>",
  });
  assert.equal(result.body.status, "ok");
  assert.match(result.body.html, /<main>Ready<\/main>/);
});

test("Babylon endpoint bundles its runtime without remote script dependencies", async () => {
  const result = await postJson("/babylon", {
    code: [
      "const scene = new BABYLON.Scene(engine);",
      "new BABYLON.FreeCamera('camera', new BABYLON.Vector3(0, 1, -5), scene);",
      "BABYLON.MeshBuilder.CreateBox('box', {}, scene);",
      "return scene;",
    ].join("\n"),
  });
  assert.equal(result.body.status, "ok");
  assert.match(result.body.html, /<!doctype html>/i);
  assert.match(result.body.html, /connect-src data: blob:/);
  assert.doesNotMatch(result.body.html, /<script\b[^>]*\bsrc\s*=/i);
});
