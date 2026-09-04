"use client";

import { useEffect } from "react";

/**
 * Proof that the client bundle arrived.
 *
 * A blocking script in <head> starts a timer that reveals the "the app did not
 * finish loading" banner. This component's only job is to cancel it, which it
 * can only do if React actually hydrated — so the banner is a genuine signal
 * rather than a guess about `navigator` or a class name that a re-render can
 * put back.
 *
 * It runs once, on mount, and renders nothing.
 */
export default function BootProbe() {
  useEffect(() => {
    const w = window as unknown as { __weaveBootTimer?: number };
    if (w.__weaveBootTimer) {
      clearTimeout(w.__weaveBootTimer);
      w.__weaveBootTimer = undefined;
    }
    // Hydration can finish after the timer has already fired — a slow device on
    // a slow connection is the exact case the banner is for, and it is also the
    // case most likely to eventually succeed. Take the banner back down.
    const banner = document.getElementById("weave-boot-warning");
    if (banner) banner.hidden = true;
  }, []);

  return null;
}
