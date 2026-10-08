"use client";

import { useEffect, useState } from "react";
import { Copy, Minus, Square, X } from "lucide-react";
import WeaveGlyph from "@/components/brand/WeaveGlyph";

declare global {
  interface Window {
    weaveDesktop?: {
      minimize: () => Promise<void>;
      toggleMaximize: () => Promise<boolean>;
      isMaximized: () => Promise<boolean>;
      closeToTray: () => Promise<void>;
      onWindowState: (callback: (state: { maximized: boolean }) => void) => () => void;
    };
  }
}

export default function DesktopTitlebar() {
  const [desktop, setDesktop] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [sw, setSw] = useState(false);

  useEffect(() => {
    const bridge = window.weaveDesktop;
    if (!bridge) return;
    setDesktop(true);
    setSw(document.documentElement.lang === "sw");
    document.body.classList.add("weave-desktop");
    bridge.isMaximized().then(setMaximized);
    const unsubscribe = bridge.onWindowState((state) => setMaximized(state.maximized));
    return () => {
      unsubscribe();
      document.body.classList.remove("weave-desktop");
    };
  }, []);

  if (!desktop) return null;

  return (
    <div className="desktop-titlebar" role="banner">
      <div className="desktop-titlebar-brand" aria-label="Weave desktop application">
        <WeaveGlyph size={18} className="desktop-titlebar-mark" />
        <span className="font-semibold tracking-[0.08em]">WEAVE</span>
        <span className="desktop-titlebar-divider" aria-hidden="true" />
        <span className="desktop-titlebar-context">{sw ? "Nafasi ya kazi" : "Research workspace"}</span>
      </div>
      <div className="desktop-window-controls">
        <button type="button" onClick={() => void window.weaveDesktop?.minimize()} aria-label={sw ? "Punguza" : "Minimize"} title={sw ? "Punguza" : "Minimize"}>
          <Minus size={14} strokeWidth={1.8} />
        </button>
        <button type="button" onClick={() => void window.weaveDesktop?.toggleMaximize()} aria-label={maximized ? (sw ? "Rejesha ukubwa" : "Restore") : (sw ? "Panua" : "Maximize")} title={maximized ? (sw ? "Rejesha ukubwa" : "Restore") : (sw ? "Panua" : "Maximize")}>
          {maximized ? <Copy size={12} strokeWidth={1.8} /> : <Square size={12} strokeWidth={1.8} />}
        </button>
        <button className="desktop-titlebar-close" type="button" onClick={() => void window.weaveDesktop?.closeToTray()} aria-label={sw ? "Ficha Weave kwenye trei" : "Minimize Weave to tray"} title={sw ? "Ficha kwenye trei" : "Minimize to tray"}>
          <X size={15} strokeWidth={1.8} />
        </button>
      </div>
    </div>
  );
}
