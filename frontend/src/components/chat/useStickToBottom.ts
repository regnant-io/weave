"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/**
 * Bottom-pinning for a streaming transcript.
 *
 * The jitter this replaces: the old code called `bottomRef.scrollIntoView()`
 * inside a rAF *after* React had already committed the new text. The growth was
 * therefore painted one frame before the scroll that compensates for it, so at
 * the exact bottom every token produced a visible up-jump-then-catch-up. On top
 * of that, the browser's own scroll anchoring was independently trying to hold
 * position and fighting the same pixels.
 *
 * The fix has four parts:
 *   1. Pin in `useLayoutEffect` — after the DOM mutation, BEFORE paint. The
 *      user never sees an unpinned frame.
 *   2. Assign `scrollTop` directly. No scrollIntoView (which can animate, and
 *      also scrolls ancestors).
 *   3. `overflow-anchor: none` on the transcript (see globals.css) so the
 *      browser stops competing for the same correction.
 *   4. A ResizeObserver, because plenty of growth is NOT a React commit —
 *      images decoding, iframes sizing, fonts swapping, a chart mounting.
 *
 * Self-induced scrolls must not be mistaken for the user scrolling away, so
 * every programmatic assignment is fenced by a flag that the scroll handler
 * checks and clears.
 */
export function useStickToBottom<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const stick = useRef(true);
  const programmatic = useRef(false);
  const [pinned, setPinned] = useState(true);
  /** Distance from bottom, exposed so the UI can show "N new" affordances. */
  const [distance, setDistance] = useState(0);

  const pin = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = ref.current;
    if (!el) return;
    programmatic.current = true;
    if (behavior === "smooth") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      // Smooth scrolling emits many events; release the fence once it settles.
      window.setTimeout(() => (programmatic.current = false), 420);
    } else {
      el.scrollTop = el.scrollHeight;
      // Same task, so the scroll event this schedules still sees the fence.
      requestAnimationFrame(() => (programmatic.current = false));
    }
    stick.current = true;
    setPinned(true);
    setDistance(0);
  }, []);

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const d = el.scrollHeight - el.scrollTop - el.clientHeight;
    setDistance(d);
    if (programmatic.current) return;
    // Hysteresis: a small band counts as "at bottom" so sub-pixel rounding and
    // the last partial line don't unstick us mid-stream.
    const next = d <= 32;
    if (next !== stick.current) {
      stick.current = next;
      setPinned(next);
    }
  }, []);

  /** Call after any content mutation that should keep the view pinned. */
  const keep = useCallback(() => {
    if (!stick.current) return;
    const el = ref.current;
    if (!el) return;
    programmatic.current = true;
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(() => (programmatic.current = false));
  }, []);

  // Growth that React didn't cause: media, iframes, font swap, late layout.
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => keep());
    // Observe the scroller's content wrapper, not the scroller itself.
    for (const child of Array.from(el.children)) ro.observe(child);
    ro.observe(el);
    return () => ro.disconnect();
  }, [keep]);

  return { ref, onScroll, pin, keep, pinned, distance, stick };
}

/** Pin synchronously after a commit, before paint. */
export function usePinAfterCommit(keep: () => void, deps: readonly unknown[]) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(keep, deps);
}
