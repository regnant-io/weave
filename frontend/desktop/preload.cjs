/* eslint-disable @typescript-eslint/no-require-imports */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("weaveDesktop", Object.freeze({
  minimize: () => ipcRenderer.invoke("window:minimize"),
  toggleMaximize: () => ipcRenderer.invoke("window:toggle-maximize"),
  isMaximized: () => ipcRenderer.invoke("window:is-maximized"),
  closeToTray: () => ipcRenderer.invoke("window:close-to-tray"),
  onWindowState: (callback) => {
    if (typeof callback !== "function") return () => {};
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("window:state", listener);
    return () => ipcRenderer.removeListener("window:state", listener);
  },
}));
