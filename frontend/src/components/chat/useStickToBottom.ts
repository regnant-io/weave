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
 * The pinning half has four parts:
 *   1. Pin in `useLayoutEffect` — after the DOM mutation, BEFORE paint. The
 *      user never sees an unpinned frame.
 *   2. Assign `scrollTop` directly. No scrollIntoView (which can animate, and
 *      also scrolls ancestors).
 *   3. `overflow-anchor: none` on the transcript (see globals.css) so the
 *      browser stops competing for the same correction.
 *   4. A ResizeObserver, because plenty of growth is NOT a React commit —
 *      images decoding, iframes sizing, fonts swapping, a chart mounting.
 *
 * ---------------------------------------------------------------------------
 * WHY THE FENCE HAD TO GO — the "cannot scroll up" bug
 * ---------------------------------------------------------------------------
 * Self-induced scrolls must not be mistaken for the user scrolling away, and
 * the previous version enforced that with a boolean fence: every programmatic
 * assignment set `programmatic = true`, and the scroll handler returned early
 * while it was set.
 *
 * That is correct only if the fence is down most of the time. During a stream
 * it never is. `keep()` runs on every commit and every ResizeObserver callback
 * — many times a frame — and each one re-raises the fence for a whole
 * animation frame. The scroll handler therefore spent the entire stream taking
 * its early return, so a real user scroll could never unstick the view: the
 * wheel moved the scroller, `keep()` yanked it back on the next commit, and the
 * user was pinned to the bottom with no way out. Pressing "scroll to bottom"
 * made it worse, because that re-armed `stick` and started the cycle again with
 * a 420ms smooth animation whose events were all fenced too.
 *
 * The fix is to stop guessing from scroll events alone:
 *
 *   * We record the exact scrollTop we last assigned. A scroll event landing on
 *     that number is ours; one landing anywhere else is the user's. No time
 *     window, no boolean, nothing that can get stuck raised.
 *   * Real input — wheel, touch, keyboard, scrollbar drag — is observed
 *     DIRECTLY. Any upward intent unsticks immediately and cancels an in-flight
 *     smooth scroll, so the user wins the pixel fight instantly rather than
 *     after the animation finishes.
 *   * `keep()` refuses to run while the user is actively touching the scroller.
 */

/** Distance from the bottom, in px, still counted as "at the bottom". */
const BOTTOM_BAND = 48;
/** A user gesture holds off auto-pinning for this long after it ends. */
const GESTURE_GRACE_MS = 220;

export function useStickToBottom<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const stick = useRef(true);
  /** The exact scrollTop we last wrote, so we can recognise our own events. */
  const ownTop = useRef(-1);
  /** True while a finger/wheel/scrollbar gesture is in progress. */
  const gesturing = useRef(false);
  /** Timestamp the last gesture ended, for the short grace window after it. */
  const gestureEnded = useRef(0);
  /** Set while `pin("smooth")` is animating, so we can cancel it on input. */
  const smoothing = useRef(false);
  /**
   * Hard deadline for the flag above.
   *
   * `smoothing` suppresses the scroll handler, so a flag that can get stuck
   * raised reintroduces exactly the bug this hook was rewritten to remove. The
   * flag normally clears when the animation reaches the bottom, but "reaches
   * the bottom" is not guaranteed — content can grow underneath it, the tab can
   * be backgrounded mid-animation, or a browser may not animate at all. The
   * timer means the suppression cannot outlive one scroll animation whatever
   * happens.
   */
  const smoothTimer = useRef<number | null>(null);

  const [pinned, setPinned] = useState(true);
  /** Distance from bottom, exposed so the UI can show "N new" affordances. */
  const [distance, setDistance] = useState(0);

  const setStick = useCallback((next: boolean) => {
    if (stick.current === next) return;
    stick.current = next;
    setPinned(next);
  }, []);

  /** Write scrollTop and remember what the browser actually settled on. */
  const writeTop = useCallback((el: HTMLElement, top: number) => {
    el.scrollTop = top;
    // Read back: the browser clamps to scrollHeight - clientHeight, and the
    // clamped value is what the scroll event will report.
    ownTop.current = el.scrollTop;
  }, []);

  const endSmooth = useCallback(() => {
    smoothing.current = false;
    if (smoothTimer.current !== null) {
      clearTimeout(smoothTimer.current);
      smoothTimer.current = null;
    }
  }, []);

  /** Halt an in-flight smooth scroll dead, wherever it currently is. */
  const cancelSmooth = useCallback((el: HTMLElement) => {
    if (!smoothing.current) return;
    endSmooth();
    const prev = el.style.scrollBehavior;
    el.style.scrollBehavior = "auto";
    // Assigning the current position stops the animation in every engine.
    el.scrollTop = el.scrollTop;
    ownTop.current = -1; // this position is now the user's, not ours
    el.style.scrollBehavior = prev;
  }, [endSmooth]);

  const pin = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      const el = ref.current;
      if (!el) return;
      if (behavior === "smooth") {
        endSmooth();
        smoothing.current = true;
        ownTop.current = -1; // a smooth run passes through many positions
        smoothTimer.current = window.setTimeout(endSmooth, 900);
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      } else {
        writeTop(el, el.scrollHeight);
      }
      setStick(true);
      setDistance(0);
    },
    [endSmooth, setStick, writeTop],
  );

  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const d = el.scrollHeight - el.scrollTop - el.clientHeight;
    setDistance(d);

    if (smoothing.current) {
      // Our own animation is running. It ends when it reaches the bottom; the
      // user interrupting it is handled by the input listeners, not here.
      if (d <= 1) endSmooth();
      return;
    }

    // Ours? Then it says nothing about what the user wants.
    if (ownTop.current >= 0 && Math.abs(el.scrollTop - ownTop.current) <= 1) return;

    ownTop.current = -1;
    setStick(d <= BOTTOM_BAND);
  }, [endSmooth, setStick]);

  /** Call after any content mutation that should keep the view pinned. */
  const keep = useCallback(() => {
    if (!stick.current) return;
    // Never fight a live gesture, or the momentum right after one. This is what
    // makes a flick upward during a fast stream actually work.
    if (gesturing.current) return;
    if (gestureEnded.current && Date.now() - gestureEnded.current < GESTURE_GRACE_MS) return;
    const el = ref.current;
    if (!el) return;
    writeTop(el, el.scrollHeight);
  }, [writeTop]);

  /*
    Direct input observation.

    Scroll events cannot distinguish "the user dragged" from "we assigned", and
    on a fast stream there is an assignment between almost every pair of user
    events. Watching the input itself removes the ambiguity entirely.
  */
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const endGesture = () => {
      gesturing.current = false;
      gestureEnded.current = Date.now();
    };

    const onWheel = (e: WheelEvent) => {
      cancelSmooth(el);
      // Any upward wheel detaches, even one pixel: the user is reading back.
      if (e.deltaY < 0) setStick(false);
      gestureEnded.current = Date.now();
    };

    const onTouchStart = () => {
      gesturing.current = true;
      cancelSmooth(el);
    };
    const onTouchMove = () => {
      gesturing.current = true;
    };
    const onTouchEnd = () => {
      // Momentum keeps scrolling after the finger lifts; the scroll handler
      // resolves the final position, so only clear the "hands on" flag.
      endGesture();
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === "PageUp" ||
        e.key === "ArrowUp" ||
        e.key === "Home" ||
        (e.key === " " && e.shiftKey)
      ) {
        cancelSmooth(el);
        setStick(false);
      }
      if (e.key === "End") pin();
    };

    // Scrollbar drag: a mousedown inside the scroller that is NOT on content
    // (i.e. beyond the client width) is the gutter.
    const onPointerDown = (e: PointerEvent) => {
      cancelSmooth(el);
      const rect = el.getBoundingClientRect();
      if (e.clientX > rect.left + el.clientWidth) {
        gesturing.current = true;
        setStick(false);
      }
    };
    const onPointerUp = () => endGesture();

    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: true });
    el.addEventListener("touchend", onTouchEnd, { passive: true });
    el.addEventListener("touchcancel", onTouchEnd, { passive: true });
    el.addEventListener("pointerdown", onPointerDown, { passive: true });
    el.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerup", onPointerUp, { passive: true });

    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", onTouchEnd);
      el.removeEventListener("touchcancel", onTouchEnd);
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [cancelSmooth, pin, setStick]);

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

  useEffect(() => endSmooth, [endSmooth]);

  return { ref, onScroll, pin, keep, pinned, distance, stick };
}

/** Pin synchronously after a commit, before paint. */
export function usePinAfterCommit(keep: () => void, deps: readonly unknown[]) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(keep, deps);
}
