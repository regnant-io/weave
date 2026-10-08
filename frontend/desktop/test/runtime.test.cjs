/* eslint-disable @typescript-eslint/no-require-imports */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");
const vm = require("node:vm");

function runtime({ packaged = false, resourcesPath = __dirname } = {}) {
  let quitCalls = 0;
  const windowEvents = new Map();
  const app = {
    isPackaged: packaged,
    setAppUserModelId() {}, setName() {},
    requestSingleInstanceLock: () => true,
    on() {}, whenReady: () => ({ then() {} }),
    quit: () => { quitCalls += 1; },
  };
  class BrowserWindow {
    constructor() {
      this.webContents = { setWindowOpenHandler() {}, on() {} };
    }
    on(name, callback) { windowEvents.set(name, callback); }
    once() {} loadURL() {} hide() { this.hidden = true; }
    close() { windowEvents.get("close")?.({ preventDefault() {} }); }
  }
  const electron = { app, BrowserWindow, ipcMain: { handle() {} } };
  const context = vm.createContext({
    require: (name) => name === "electron" ? electron
      : name === "./browser-service.cjs" ? {} : require(name),
    process: { ...process, resourcesPath }, __dirname: path.resolve(__dirname, ".."),
    URL, setTimeout, clearTimeout,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "main.cjs"), "utf8"), context);
  vm.runInContext('webUrl = "http://127.0.0.1:3200";', context);
  return { context, windowEvents, quits: () => quitCalls };
}

test("desktop navigation requires the exact loopback origin", () => {
  const { context } = runtime();
  for (const url of ["http://127.0.0.1:3200/app", "http://127.0.0.1:3200/?x=1"]) {
    assert.equal(vm.runInContext(`isAppUrl(${JSON.stringify(url)})`, context), true);
  }
  for (const url of ["http://127.0.0.1:32001/", "https://127.0.0.1:3200/", "file:///x", "invalid"]) {
    assert.equal(vm.runInContext(`isAppUrl(${JSON.stringify(url)})`, context), false);
  }
});

test("closing without a tray exits instead of hiding an unreachable window", () => {
  const { context, windowEvents, quits } = runtime();
  vm.runInContext("createWindow()", context);
  let prevented = false;
  windowEvents.get("close")({ preventDefault() { prevented = true; } });
  assert.equal(quits(), 1);
  assert.equal(prevented, false);
});

test("closing with a tray keeps the app available", () => {
  const { context, windowEvents, quits } = runtime();
  vm.runInContext("tray = {}; createWindow()", context);
  let prevented = false;
  windowEvents.get("close")({ preventDefault() { prevented = true; } });
  assert.equal(quits(), 0);
  assert.equal(prevented, true);
  assert.equal(vm.runInContext("mainWindow.hidden", context), true);
});

test("Windows node shim executes code with a quoted preload path", { skip: process.platform !== "win32" }, () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "weave shim test "));
  assert.equal(path.dirname(path.resolve(tempRoot)), path.resolve(os.tmpdir()));
  try {
    const { context } = runtime({ packaged: true, resourcesPath: tempRoot });
    const toolDir = vm.runInContext(`desktopTools(${JSON.stringify(tempRoot)})`, context);
    const batch = path.join(toolDir, "node.cmd").replaceAll("'", "''");
    const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", `& '${batch}' -e 'console.log(42)'`], {
      encoding: "utf8", windowsHide: true, timeout: 20_000,
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout.trim(), "42");
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});
