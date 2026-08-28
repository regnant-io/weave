"use client";

import { useEffect } from "react";

/**
 * Publishes the on-screen keyboard's height as `--kb-inset` on <html>.
 *
 * iOS does not shrink the LAYOUT viewport when the keyboard opens — it only
 * shrinks the VISUAL viewport and scrolls the page. A composer anchored to
 * `bottom: 0` therefore ends up underneath the keyboard, which is exactly the
 * "input hides below the screen" bug on phones. Reading `visualViewport` and
 * lifting the composer by the difference is the only reliable fix; there is no
 * CSS unit that expresses it.
 *
 * Android/Chrome usually resizes the layout viewport instead, in which case the
 * computed inset is ~0 and this is a no-op. Browsers without `visualViewport`
 * (very old Android WebView) also get 0 and simply keep the previous behaviour.
 */
export function useViewportInsets(): void {
  useEffect(() => {
    const vv = typeof window !== "undefined" ? window.visualViewport : undefined;
    if (!vv) return;

    const root = document.documentElement;
    let frame = 0;

    const apply = () => {
      frame = 0;
      // How much of the layout viewport the keyboard (and any browser chrome
      // overlay) is covering at the bottom.
      const covered = window.innerHeight - vv.height - vv.offsetTop;
      // Sub-pixel noise and the iOS URL bar produce small non-zero values while
      // no keyboard is open; a threshold keeps the composer still.
      const inset = covered > 80 ? Math.round(covered) : 0;
      root.style.setProperty("--kb-inset", `${inset}px`);
    };

    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(apply);
    };

    apply();
    vv.addEventListener("resize", schedule);
    vv.addEventListener("scroll", schedule);
    window.addEventListener("orientationchange", schedule);

    return () => {
      if (frame) cancelAnimationFrame(frame);
      vv.removeEventListener("resize", schedule);
      vv.removeEventListener("scroll", schedule);
      window.removeEventListener("orientationchange", schedule);
      root.style.setProperty("--kb-inset", "0px");
    };
  }, []);
}
