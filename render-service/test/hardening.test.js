import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { app } from "../server.js";
import { adoptHarnessContract } from "../lib/babylon.js";
import { screenCode } from "../lib/custom.js";

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

async function post(path, body) {
  const response = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let json = {};
  try { json = JSON.parse(text); } catch { /* svg/html bodies */ }
  return { status: response.status, json, text };
}

const values = [{ region: "Dodoma", value: 4 }, { region: "Mwanza", value: 7 }];

test("chart data is never loaded from a URL or the local disk", async () => {
  // Vega's default Node loader read this service's own package.json into a chart.
  for (const url of ["package.json", "file:///etc/passwd", "http://169.254.169.254/latest"]) {
    const { status, json } = await post("/chart", {
      format: "json",
      spec: { mark: "bar", data: { url }, encoding: { x: { field: "a", type: "nominal" } } },
    });
    assert.equal(status, 400, url);
    assert.match(json.error, /inline data only/);
  }
});

test("a Vega-Lite spec without $schema is compiled as Vega-Lite", async () => {
  const { status } = await post("/chart", {
    format: "json",
    spec: { mark: "bar", data: { values }, encoding: {
      x: { field: "region", type: "nominal" }, y: { field: "value", type: "quantitative" } } },
  });
  assert.equal(status, 200);
});

test("an encoding field missing from the data is named, with the fields that exist", async () => {
  const { status, json } = await post("/chart", {
    format: "json",
    spec: { mark: "point", data: { values }, encoding: {
      x: { field: "Region", type: "nominal" }, y: { field: "value", type: "quantitative" } } },
  });
  assert.equal(status, 400);
  assert.match(json.error, /`Region`/);
  assert.match(json.error, /region, value/);
});

test("a chart that draws axes but no data marks is refused", async () => {
  const { status, json } = await post("/chart", {
    format: "json",
    spec: { mark: "line", data: { values: [] }, encoding: {
      x: { field: "region", type: "nominal" }, y: { field: "value", type: "quantitative" } } },
  });
  assert.equal(status, 400);
  assert.match(json.error, /no marks/);
});

test("transform outputs count as fields", async () => {
  const { status } = await post("/chart", {
    format: "json",
    spec: { mark: "bar", data: { values },
      transform: [{ calculate: "datum.value * 2", as: "double" }],
      encoding: { x: { field: "region", type: "nominal" }, y: { field: "double", type: "quantitative" } } },
  });
  assert.equal(status, 200);
});

test("ordinary variables named parent and top are not sandbox escapes", () => {
  assert.deepEqual(screenCode("const parent = new BABYLON.TransformNode('p'); parent.position.x = 1;"), []);
  assert.deepEqual(screenCode("const top = box(); top.position.y = 2; const x = d.parent.x;"), []);
  assert.deepEqual(screenCode("window.parent.postMessage('x', '*')"), ["parent access"]);
  assert.deepEqual(screenCode("top.location = 'https://evil.example'"), ["top access"]);
});

test("Babylon playground boilerplate is adapted to the harness", async () => {
  const code = [
    'const canvas = document.getElementById("renderCanvas");',
    "const engine = new BABYLON.Engine(canvas, true);",
    "const createScene = function () {",
    "  const scene = new BABYLON.Scene(engine);",
    "  new BABYLON.ArcRotateCamera('c', 0, 1, 10, BABYLON.Vector3.Zero(), scene);",
    "  return scene;",
    "};",
    "const scene = createScene();",
    "engine.runRenderLoop(() => scene.render());",
  ].join("\n");
  const { status, json } = await post("/babylon", { code });
  assert.equal(status, 200, json.error);
  assert.equal(json.notes.length, 2);
});

test("the harness contract rewrite keeps statements and adds an unreachable-when-returned fallback", () => {
  const { code, adjustments } = adoptHarnessContract("let engine = make();\nreturn scene;");
  assert.match(code, /engine = engine \|\| make\(\)/);
  assert.match(code, /typeof createScene === 'function'/);
  assert.equal(adjustments.length, 1);
  assert.deepEqual(adoptHarnessContract("const scene = x; return scene;").adjustments, []);
});

test("the service's own inlined libraries are not linted as the model's code", async () => {
  // Babylon contains fetch() and thousands of braces in strings; linting it
  // reported a network request and truncation on every 3D scene.
  const { status, json } = await post("/babylon", {
    code: "const scene = new BABYLON.Scene(engine); new BABYLON.FreeCamera('c', BABYLON.Vector3.Zero(), scene); return scene;",
  });
  assert.equal(status, 200);
  const lint = await post("/verify", { html: json.html });
  assert.deepEqual(lint.json.warnings.filter((w) => /network|truncated/.test(w)), []);
});

test("the createScene fallback passes every harness argument", () => {
  const { code } = adoptHarnessContract(
    "const createScene = (engine, canvas, BABYLON) => new BABYLON.Scene(engine);");
  assert.match(code, /createScene\(engine, canvas, BABYLON, assets\)/);
});
