/* eslint-disable @typescript-eslint/no-require-imports */
/* A loopback browser worker backed by Electron's bundled Chromium.
 *
 * Speaks the small subset of the Browserless HTTP API the backend uses
 * (/function, /screenshot, /content), so the same probe code runs against a
 * Browserless container on a server and against this worker on a desktop.
 *
 * Artifact HTML is loaded from a private temporary FILE, never a data: URL.
 * Chromium refuses URLs longer than 2 MB with ERR_INVALID_URL, and every 3D
 * artifact inlines its engine (Babylon alone is ~7 MB). Loading those as data:
 * URLs failed every 3D scene with "the document failed to load" on desktop.
 * The model was then sent off to "repair" a page that had nothing wrong with it.
 */
const { BrowserWindow, session } = require("electron");
const http = require("node:http");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const MAX_BODY = 26 * 1024 * 1024;
const MAX_BROWSERS = 2;
/** How long a request may wait for a free browser before the worker says busy. */
const QUEUE_TIMEOUT_MS = 45_000;
const LOAD_TIMEOUT_MS = 25_000;
const PARTITION = "weave-probe";

/** Console noise Electron adds to unpackaged runs; never a page defect. */
const IGNORED_CONSOLE = [/Electron Security Warning/i];

let active = 0;
const waiters = [];
/** webContents id -> request policy, read by the one shared request filter. */
const policies = new Map();
let probeSession;

function send(res, code, body, type = "application/json") {
  const data = Buffer.isBuffer(body) ? body : Buffer.from(type === "application/json" ? JSON.stringify(body) : body);
  res.writeHead(code, { "content-type": type, "content-length": data.length, "cache-control": "no-store" });
  res.end(data);
}

async function readJson(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY) throw new Error("request is too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Wait for a browser slot. Queued rather than refused: the backend runs
 *  artifact checks concurrently, and "busy" used to skip verification. */
function acquire() {
  if (active < MAX_BROWSERS) {
    active += 1;
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const waiter = { resolve, timer: null };
    waiter.timer = setTimeout(() => {
      const index = waiters.indexOf(waiter);
      if (index >= 0) waiters.splice(index, 1);
      reject(new Error("browser worker is busy"));
    }, QUEUE_TIMEOUT_MS);
    waiters.push(waiter);
  });
}

function release() {
  const next = waiters.shift();
  if (next) {
    clearTimeout(next.timer);
    next.resolve();
  } else {
    active = Math.max(0, active - 1);
  }
}

/** One in-memory session for every probe, with a single request filter.
 *  Electron allows only one onBeforeRequest listener per session, so the filter
 *  looks up the policy of whichever window made the request. */
function getProbeSession() {
  if (probeSession) return probeSession;
  probeSession = session.fromPartition(PARTITION);
  probeSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  probeSession.webRequest.onBeforeRequest((details, callback) => {
    const policy = policies.get(details.webContentsId);
    if (!policy) return callback({ cancel: false });
    const url = details.url;
    if (/^https?:/i.test(url)) {
      policy.networkAttempts.push(url.slice(0, 300));
      return callback({ cancel: !policy.allowNetwork });
    }
    if (/^file:/i.test(url)) {
      // The document itself, and nothing else on the local disk.
      return callback({ cancel: url !== policy.documentUrl });
    }
    return callback({ cancel: false });
  });
  probeSession.webRequest.onCompleted((details) => {
    const policy = policies.get(details.webContentsId);
    if (policy && details.statusCode >= 400) {
      policy.failedResources.push({ url: details.url.slice(0, 300), status: details.statusCode });
    }
  });
  return probeSession;
}

/** Normalise `console-message` across Electron versions.
 *  Electron 35+ passes one event object with string `level`/`message`; older
 *  versions pass (event, level:number, message, line, sourceId). */
function consoleDetail(args) {
  const [first, second, third] = args;
  if (first && typeof first === "object" && typeof first.message === "string") {
    return { level: first.level, message: first.message };
  }
  if (second && typeof second === "object") return { level: second.level, message: second.message };
  return { level: second, message: third };
}

function normaliseLevel(level) {
  if (level === 3 || level === "error") return "error";
  if (level === 2 || level === "warning" || level === "warn") return "warning";
  return "";
}

async function withTimeout(promise, ms, message) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_resolve, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function inspect(payload, action) {
  const context = payload.context || payload;
  const html = typeof context.html === "string" ? context.html : "";
  const url = typeof context.url === "string" ? context.url : "";
  if (!html && !url) throw new Error("html or url is required");
  if (url && !/^https?:\/\//i.test(url)) throw new Error("only HTTP URLs may be opened");

  await acquire();
  let win;
  let tempDir = "";
  try {
    return await runInspection(context, html, url, action, (created, dir) => {
      win = created;
      tempDir = dir;
    });
  } finally {
    if (win && !win.isDestroyed()) {
      policies.delete(win.webContents.id);
      win.destroy();
    }
    if (tempDir) fs.rm(tempDir, { recursive: true, force: true }, () => {});
    release();
  }
}

async function runInspection(context, html, url, action, track) {
  const width = Math.max(320, Math.min(1920, Number(context.width) || 1100));
  const height = Math.max(240, Math.min(1200, Number(context.height) || 720));
  let tempDir = "";
  let documentUrl = "";
  if (html) {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "weave-probe-"));
    track(undefined, tempDir);
    const file = path.join(tempDir, "index.html");
    fs.writeFileSync(file, html, "utf8");
    documentUrl = pathToFileURL(file).href;
  }

  const ses = getProbeSession();
  const win = new BrowserWindow({
    show: false, width, height, useContentSize: true,
    webPreferences: { session: ses, sandbox: true, contextIsolation: true, nodeIntegration: false,
      backgroundThrottling: false, webSecurity: true, offscreen: true },
  });
  track(win, tempDir);
  const contents = win.webContents;
  const consoleErrors = [];
  const pageErrors = [];
  const networkAttempts = [];
  const failedResources = [];
  policies.set(contents.id, {
    allowNetwork: !html, documentUrl, networkAttempts, failedResources,
  });
  contents.on("console-message", (...args) => {
    const detail = consoleDetail(args);
    const level = normaliseLevel(detail.level);
    const text = String(detail.message || "");
    if (!level || IGNORED_CONSOLE.some((re) => re.test(text))) return;
    consoleErrors.push({ level, text: text.slice(0, 600) });
  });
  contents.on("render-process-gone", (_event, detail) => pageErrors.push(`renderer stopped: ${detail.reason}`));

  const result = { loaded: false, consoleErrors, pageErrors, networkAttempts, failedResources };
  try {
    await withTimeout(win.loadURL(documentUrl || url), LOAD_TIMEOUT_MS, "page load timed out");
    result.loaded = true;
    if (action === "content") return await contents.executeJavaScript("document.documentElement.outerHTML");
    const settle = Math.max(100, Math.min(10000, Number(context.settleMs) || 1400));
    const deadline = Date.now() + settle;
    while (Date.now() < deadline) {
      const ready = await contents.executeJavaScript(`(() => {
        const err = document.getElementById('err');
        if (err && err.textContent.trim() && getComputedStyle(err).display !== 'none') return true;
        const boot = document.getElementById('boot');
        return boot ? boot.classList.contains('gone') : false;
      })()`);
      if (ready) { await delay(260); break; }
      await delay(100);
    }
    result.paint = await contents.executeJavaScript(`(() => {
      const body = document.body;
      const out = { textLen: (body?.innerText || '').trim().length,
        canvases: 0, paintedCanvases: 0, svgs: document.querySelectorAll('svg').length,
        elements: body ? body.querySelectorAll('*').length : 0,
        bodyHeight: body ? Math.round(body.getBoundingClientRect().height) : 0,
        visibleError: '', title: document.title || '' };
      for (const el of document.querySelectorAll('#err, .weave-error, [data-weave-error]')) {
        const style = getComputedStyle(el);
        if (el.textContent.trim() && style.display !== 'none' &&
            style.visibility !== 'hidden' && style.opacity !== '0') {
          out.visibleError = el.textContent.trim().slice(0, 600); break;
        }
      }
      for (const canvas of document.querySelectorAll('canvas')) {
        out.canvases++;
        if (!canvas.width || !canvas.height) continue;
        try {
          const blank = document.createElement('canvas');
          blank.width = canvas.width; blank.height = canvas.height;
          if (canvas.toDataURL() !== blank.toDataURL()) out.paintedCanvases++;
        } catch { out.paintedCanvases++; }
      }
      return out;
    })()`);
    try {
      const image = await contents.capturePage();
      if (action === "screenshot") return image.toPNG();
      result.screenshot = image.toJPEG(62).toString("base64");
    } catch (error) { pageErrors.push(`screenshot failed: ${error.message}`); }
    return { data: result, type: "application/json" };
  } catch (error) {
    result.loadError = String(error.message || error).slice(0, 400);
    return { data: result, type: "application/json" };
  }
}

function startBrowserService(port, log) {
  const server = http.createServer(async (req, res) => {
    if (req.method === "GET" && req.url === "/health") {
      return send(res, 200, { status: "ok", active, queued: waiters.length });
    }
    if (req.method !== "POST" || !["/function", "/screenshot", "/content"].includes(req.url)) {
      return send(res, 404, { error: "not found" });
    }
    try {
      const payload = await readJson(req);
      const action = req.url.slice(1);
      const result = await inspect(payload, action);
      if (Buffer.isBuffer(result)) return send(res, 200, result, "image/png");
      if (typeof result === "string") return send(res, 200, result, "text/html; charset=utf-8");
      return send(res, 200, result);
    } catch (error) {
      log?.write(`Browser worker: ${error.stack || error}\n`);
      const code = /too large/.test(error.message) ? 413 : /busy/.test(error.message) ? 503 : 500;
      return send(res, code, { error: error.message });
    }
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

module.exports = { startBrowserService, consoleDetail, normaliseLevel };
