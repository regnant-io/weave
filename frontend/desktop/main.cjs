/* eslint-disable @typescript-eslint/no-require-imports */
const { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, shell, Tray } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const { createServer } = require("node:net");
const { randomBytes } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { startBrowserService } = require("./browser-service.cjs");

const APP_ID = "org.weave.platform";
const APP_NAME = "Weave";
let mainWindow;
let tray;
let quitting = false;
let backendProcess;
let frontendProcess;
let renderProcess;
let browserServer;
let logStream;
let apiPort;
let webPort;
let renderPort;
let browserPort;
let webUrl;
const restartCounts = new Map();

app.setAppUserModelId(APP_ID);
app.setName(APP_NAME);
if (process.env.WEAVE_USER_DATA_DIR) {
  const userDataDir = path.resolve(process.env.WEAVE_USER_DATA_DIR);
  fs.mkdirSync(userDataDir, { recursive: true });
  app.setPath("userData", userDataDir);
}
const hasInstanceLock = app.requestSingleInstanceLock();
if (!hasInstanceLock) app.quit();
else app.on("second-instance", () => showWindow());

function assetPath(name) {
  return app.isPackaged ? path.join(process.resourcesPath, "assets", name)
    : path.join(__dirname, "assets", name);
}

function isAppUrl(url) {
  try { return new URL(url).origin === new URL(webUrl).origin; }
  catch { return false; }
}

function getPort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close((error) => error ? reject(error) : resolve(address.port));
    });
  });
}

function executableFor(resources) {
  const name = process.platform === "win32" ? "weave-backend.exe" : "weave-backend";
  return path.join(resources, name);
}

/** Loaded into every workspace node process on Windows; see desktopTools. */
const HIDE_WINDOWS_PRELOAD = `"use strict";
const cp = require("child_process");
for (const name of ["spawn", "spawnSync", "execFile", "execFileSync", "exec", "execSync", "fork"]) {
  const original = cp[name];
  if (typeof original !== "function") continue;
  cp[name] = function (file, ...rest) {
    let at = rest.findIndex((a) => a && typeof a === "object" && !Array.isArray(a));
    if (at === -1) {
      at = name.startsWith("exec") && !name.startsWith("execFile") ? 0 : (Array.isArray(rest[0]) ? 1 : 0);
      rest.splice(at, 0, {});
    }
    if (rest[at].windowsHide === undefined) rest[at] = { ...rest[at], windowsHide: true };
    return original.call(this, file, ...rest);
  };
}
`;

function desktopTools(dataRoot) {
  if (!app.isPackaged) return "";
  const bin = path.join(dataRoot, "tools");
  fs.mkdirSync(bin, { recursive: true });
  const exe = process.execPath;
  const backend = executableFor(path.join(process.resourcesPath, "backend"));
  const npmCli = path.join(process.resourcesPath, "npm", "bin", "npm-cli.js");
  // npx is how every scaffolder is invoked (`npx create-vite`, `npx tsc`).
  // Without a shim the model's first command of a new project failed with
  // "npx is not recognized".
  const npxCli = path.join(process.resourcesPath, "npm", "bin", "npx-cli.js");
  if (process.platform === "win32") {
    // "node" here is Weave.exe, a GUI-subsystem binary with no console. Any
    // console program it starts with inherited stdio (npm runs every script
    // that way) gets a brand-new console, and Windows opens a terminal window
    // for it outside the app. Defaulting windowsHide to true for every
    // child_process call (CREATE_NO_WINDOW) keeps the whole tree invisible.
    fs.writeFileSync(path.join(bin, "weave-hide-windows.cjs"), HIDE_WINDOWS_PRELOAD);
    // NODE_OPTIONS parses backslashes as escapes, even on Windows. Forward
    // slashes preserve the preload path when node/npm actually execute code.
    const env = `set "ELECTRON_RUN_AS_NODE=1"\r\nset "WEAVE_HIDE_PRELOAD=%~dp0weave-hide-windows.cjs"\r\nset "WEAVE_HIDE_PRELOAD=%WEAVE_HIDE_PRELOAD:\\=/%"\r\nset "NODE_OPTIONS=--require "%WEAVE_HIDE_PRELOAD%" %NODE_OPTIONS%"\r\n`;
    fs.writeFileSync(path.join(bin, "node.cmd"),
      `@echo off\r\n${env}"${exe}" %*\r\n`);
    fs.writeFileSync(path.join(bin, "npm.cmd"),
      `@echo off\r\n${env}"${exe}" "${npmCli}" %*\r\n`);
    fs.writeFileSync(path.join(bin, "npx.cmd"),
      `@echo off\r\n${env}"${exe}" "${npxCli}" %*\r\n`);
    fs.writeFileSync(path.join(bin, "python.cmd"),
      `@echo off\r\n"${backend}" weave-python %*\r\n`);
  } else {
    const wrappers = {
      node: `#!/bin/sh\nELECTRON_RUN_AS_NODE=1 exec "${exe}" "$@"\n`,
      npm: `#!/bin/sh\nELECTRON_RUN_AS_NODE=1 exec "${exe}" "${npmCli}" "$@"\n`,
      npx: `#!/bin/sh\nELECTRON_RUN_AS_NODE=1 exec "${exe}" "${npxCli}" "$@"\n`,
      python: `#!/bin/sh\nexec "${backend}" weave-python "$@"\n`,
    };
    for (const [name, source] of Object.entries(wrappers)) {
      const file = path.join(bin, name);
      fs.writeFileSync(file, source);
      fs.chmodSync(file, 0o755);
    }
  }
  return bin;
}

function managedSpawn(label, executable, args, options, assign) {
  const start = () => {
    if (quitting) return undefined;
    const startedAt = Date.now();
    const child = spawn(executable, args, { ...options, windowsHide: true });
    assign(child);
    child.stdout?.pipe(logStream, { end: false });
    child.stderr?.pipe(logStream, { end: false });
    child.on("error", (error) => {
      if (!quitting) logStream.write(`${label}: ${error.message}\n`);
    });
    child.on("close", (code) => {
      if (quitting) return;
      const attempts = Date.now() - startedAt > 60_000
        ? 1 : (restartCounts.get(label) || 0) + 1;
      restartCounts.set(label, attempts);
      logStream.write(`${label} stopped with code ${code}; restart ${attempts}/3\n`);
      if (attempts <= 3) {
        setTimeout(start, attempts * 1000);
      } else {
        dialog.showErrorBox("Weave service stopped", `${label} could not stay running. See the desktop log in your Weave data directory.`);
      }
    });
    return child;
  };
  return start();
}

function launchServices() {
  const dataRoot = path.join(app.getPath("userData"), "data");
  fs.mkdirSync(dataRoot, { recursive: true });
  fs.mkdirSync(path.join(dataRoot, "logs"), { recursive: true });
  fs.mkdirSync(path.join(dataRoot, "storage"), { recursive: true });
  fs.mkdirSync(path.join(dataRoot, "workspaces"), { recursive: true });
  const toolDir = desktopTools(dataRoot);
  const secretFile = path.join(dataRoot, "secret.key");
  if (!fs.existsSync(secretFile)) {
    fs.writeFileSync(secretFile, randomBytes(48).toString("hex"), { mode: 0o600 });
  }
  const logFile = path.join(dataRoot, "logs", "desktop.log");
  try {
    // Every model request is logged, so an unrotated log grows without bound.
    // Keep one previous generation, which is what anyone debugging needs.
    if (fs.statSync(logFile).size > 10 * 1024 * 1024) {
      fs.rmSync(`${logFile}.1`, { force: true });
      fs.renameSync(logFile, `${logFile}.1`);
    }
  } catch { /* no log yet */ }
  logStream = fs.createWriteStream(logFile, { flags: "a" });
  return Promise.resolve().then(async () => {
    const reserved = new Set();
    const allocate = async () => {
      let port;
      do { port = await getPort(); } while (reserved.has(port));
      reserved.add(port);
      return port;
    };
    apiPort = await allocate();
    webPort = await allocate();
    renderPort = await allocate();
    browserPort = await allocate();
    webUrl = `http://127.0.0.1:${webPort}`;
    // The browser worker and the render service are CAPABILITIES, not the app.
    // Either failing used to abort startup with "Weave could not start"; now
    // the backend is simply not told about a service that did not come up,
    // and reports those tools as unavailable instead.
    try {
      browserServer = await startBrowserService(browserPort, logStream);
    } catch (error) {
      logStream.write(`Browser worker could not start: ${error.message}\n`);
      browserServer = undefined;
    }
    const renderRoot = app.isPackaged
      ? path.join(process.resourcesPath, "render")
      : path.resolve(__dirname, "..", "..", "render-service");
    const renderNode = app.isPackaged ? process.execPath : (process.env.WEAVE_NODE_PATH || "node");
    renderProcess = managedSpawn("Render service", renderNode, [path.join(renderRoot, "server.js")], {
      cwd: renderRoot,
      env: {
        ...process.env,
        ...(app.isPackaged ? { ELECTRON_RUN_AS_NODE: "1" } : {}),
        HOST: "127.0.0.1",
        PORT: String(renderPort),
      },
    }, (child) => { renderProcess = child; });
    let renderReady = true;
    try {
      await waitForHttp(`http://127.0.0.1:${renderPort}/health`, 90_000);
    } catch (error) {
      renderReady = false;
      logStream.write(`Render service did not become ready: ${error.message}\n`);
    }
    const dataEnv = {
      WEAVE_ENVIRONMENT: "desktop",
      WEAVE_DEBUG: "false",
      WEAVE_DATA_DIR: dataRoot,
      WEAVE_DATABASE_URL: `sqlite:///${path.join(dataRoot, "weave.db").replace(/\\/g, "/")}`,
      WEAVE_STORAGE_BACKEND: "local",
      WEAVE_STORAGE_LOCAL_DIR: path.join(dataRoot, "storage"),
      WEAVE_WORKSPACE_ROOT: path.join(dataRoot, "workspaces"),
      WEAVE_WORKSPACE_ENABLED: "true",
      WEAVE_DESKTOP_TOOL_DIR: toolDir,
      WEAVE_SECRET_KEY: fs.readFileSync(secretFile, "utf8").trim(),
      WEAVE_LLM_BACKEND: "auto",
      WEAVE_OLLAMA_HOST: process.env.WEAVE_OLLAMA_HOST || "http://127.0.0.1:11434",
      WEAVE_RENDER_URL: renderReady ? `http://127.0.0.1:${renderPort}` : "",
      WEAVE_GOTENBERG_URL: "",
      WEAVE_BROWSERLESS_URL: browserServer ? `http://127.0.0.1:${browserPort}` : "",
      WEAVE_BIND_HOST: "127.0.0.1",
      WEAVE_BIND_PORT: String(apiPort),
    };

    if (app.isPackaged) {
      const backendExe = executableFor(path.join(process.resourcesPath, "backend"));
      const serverRoot = path.join(process.resourcesPath, "app");
      const backendEnv = { ...process.env, ...dataEnv,
        PATH: toolDir ? `${toolDir}${path.delimiter}${process.env.PATH || ""}` : process.env.PATH };
      backendProcess = managedSpawn("Backend", backendExe, [],
        { cwd: dataRoot, env: backendEnv }, (child) => { backendProcess = child; });
      await waitForHttp(`http://127.0.0.1:${apiPort}/health`, 90_000);

      const electronNode = process.execPath;
      const webEnv = {
        ...process.env,
        WEAVE_ENVIRONMENT: "desktop",
        NODE_ENV: "production",
        ELECTRON_RUN_AS_NODE: "1",
        HOSTNAME: "127.0.0.1",
        PORT: String(webPort),
        WEAVE_API_BASE: `http://127.0.0.1:${apiPort}`,
        NEXT_TELEMETRY_DISABLED: "1",
      };
      frontendProcess = managedSpawn("Web server", electronNode, [path.join(serverRoot, "server.js")], {
        cwd: serverRoot,
        env: webEnv,
      }, (child) => { frontendProcess = child; });
    } else {
      const backendRoot = path.resolve(__dirname, "..", "..", "backend");
      const python = process.env.WEAVE_PYTHON || "python";
      backendProcess = managedSpawn("Backend", python, ["-m", "app.desktop_entry"], {
        cwd: backendRoot,
        env: { ...process.env, ...dataEnv, PYTHONPATH: backendRoot },
      }, (child) => { backendProcess = child; });
      await waitForHttp(`http://127.0.0.1:${apiPort}/health`, 90_000);
      const node = process.env.WEAVE_NODE_PATH || "node";
      frontendProcess = managedSpawn("Web server", node, [path.join(__dirname, "..", "node_modules", "next", "dist", "bin", "next"), "start", "-p", String(webPort), "-H", "127.0.0.1"], {
        cwd: path.resolve(__dirname, ".."),
        env: {
          ...process.env,
          WEAVE_ENVIRONMENT: "desktop",
          NODE_ENV: "production",
          WEAVE_API_BASE: `http://127.0.0.1:${apiPort}`,
        },
      }, (child) => { frontendProcess = child; });
    }
    await waitForHttp(webUrl, 90_000);
  });
}

async function waitForHttp(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1800) });
      if (response.ok) return;
      lastError = new Error(`Service returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Weave service did not become ready: ${lastError?.message || url}`);
}

function createWindow() {
  const icon = assetPath("weave.png");
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 960,
    minWidth: 900,
    minHeight: 620,
    show: false,
    frame: false,
    backgroundColor: "#f4f6f8",
    autoHideMenuBar: true,
    icon: fs.existsSync(icon) ? icon : undefined,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged,
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isAppUrl(url)) {
      event.preventDefault();
      if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    }
  });
  mainWindow.webContents.on("did-fail-load", (_event, code, _description, url, isMainFrame) => {
    if (quitting || !isMainFrame || code === -3 || !isAppUrl(url)) return;
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.loadURL(webUrl);
    }, 1500);
  });
  mainWindow.on("maximize", sendWindowState);
  mainWindow.on("unmaximize", sendWindowState);
  mainWindow.on("close", (event) => {
    if (quitting) return;
    if (!tray) {
      quitting = true;
      app.quit();
      return;
    }
    event.preventDefault();
    mainWindow.hide();
  });
  mainWindow.on("closed", () => { mainWindow = null; });
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.loadURL(webUrl);
}

function sendWindowState() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("window:state", { maximized: mainWindow.isMaximized() });
  }
}

function showWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function createTray() {
  const iconPath = assetPath(process.platform === "win32" ? "weave.ico" : "weave.png");
  if (!fs.existsSync(iconPath)) return;
  tray = new Tray(nativeImage.createFromPath(iconPath));
  tray.setToolTip(APP_NAME);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Open Weave", click: showWindow },
    { label: "Hide window", click: () => mainWindow?.hide() },
    { type: "separator" },
    { label: "Exit Weave", click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on("double-click", showWindow);
  tray.on("click", showWindow);
}

ipcMain.handle("window:minimize", () => mainWindow?.minimize());
ipcMain.handle("window:toggle-maximize", () => {
  if (!mainWindow) return false;
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
  sendWindowState();
  return mainWindow.isMaximized();
});
ipcMain.handle("window:is-maximized", () => Boolean(mainWindow?.isMaximized()));
ipcMain.handle("window:close-to-tray", () => mainWindow?.close());

app.whenReady().then(async () => {
  if (!hasInstanceLock) return;
  try {
    await launchServices();
    createTray();
    createWindow();
    app.on("activate", showWindow);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await dialog.showMessageBox({
      type: "error",
      title: "Weave could not start",
      message: "A local service did not start correctly.",
      detail: `${message}\n\nLogs: ${path.join(app.getPath("userData"), "data", "logs", "desktop.log")}`,
      buttons: ["Exit"],
    });
    quitting = true;
    app.quit();
  }
});

app.on("before-quit", () => {
  quitting = true;
  browserServer?.close();
  for (const child of [frontendProcess, backendProcess, renderProcess]) {
    if (!child || child.killed) continue;
    if (process.platform === "win32" && child.pid) {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"],
        { windowsHide: true, timeout: 6000 });
    } else {
      child.kill();
    }
  }
  logStream?.end();
});
