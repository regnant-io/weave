"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * Rate-smoothed token drain.
 *
 * Raw SSE arrives in lumps: the network coalesces, and a local Ollama emits a
 * whole word (sometimes a whole sentence) per message. Flushing whatever landed
 * once per frame — the old behaviour — reproduces that lumpiness exactly, so
 * text arrives in visible chunks with dead frames between them.
 *
 * Instead we treat arriving text as a reservoir and release it at a controlled
 * rate, so the reader sees continuous flow regardless of how bursty the source
 * is. The rate adapts: we always aim to empty the reservoir within
 * DRAIN_TARGET_MS, so we track a fast model closely and never build a lag the
 * user would notice, while a slow model still reads as a steady hand rather
 * than a stutter.
 *
 * There is deliberately no caret. Growth is the only motion cue.
 */

const FRAME_MS = 1000 / 60;
/** Empty whatever is buffered within roughly this long. */
const DRAIN_TARGET_MS = 140;
/** Never slower than this, or a trickle of tokens looks frozen. */
const MIN_CHARS_PER_FRAME = 1;
/** Backlog past this means the model is way ahead; dump faster to catch up. */
const FLOOD_THRESHOLD = 900;

export function useSmoothStream(onChars: (chunk: string) => void) {
  const buffer = useRef("");
  const raf = useRef<number | null>(null);
  const running = useRef(false);
  const finishing = useRef(false);
  const onCharsRef = useRef(onChars);
  onCharsRef.current = onChars;

  const tick = useCallback(() => {
    const pending = buffer.current.length;

    if (pending === 0) {
      if (finishing.current) {
        running.current = false;
        finishing.current = false;
        raf.current = null;
        return;
      }
      raf.current = requestAnimationFrame(tick);
      return;
    }

    const framesInTarget = Math.max(1, DRAIN_TARGET_MS / FRAME_MS);
    let n = Math.ceil(pending / framesInTarget);

    if (pending > FLOOD_THRESHOLD) {
      // Far behind: release aggressively so latency stays bounded. Still not
      // the whole buffer, so it reads as fast typing rather than a paste.
      n = Math.ceil(pending / 3);
    } else if (finishing.current) {
      // Stream closed — land the tail promptly but still smoothly.
      n = Math.max(n, Math.ceil(pending / 8));
    }
    n = Math.max(MIN_CHARS_PER_FRAME, n);

    // Prefer to break on whitespace so words don't visibly assemble letter by
    // letter mid-word, which reads as glitchy rather than fluid.
    if (n < pending) {
      const window = buffer.current.slice(n, Math.min(pending, n + 12));
      const ws = window.search(/\s/);
      if (ws >= 0) n += ws + 1;
    }

    const chunk = buffer.current.slice(0, n);
    buffer.current = buffer.current.slice(n);
    onCharsRef.current(chunk);

    raf.current = requestAnimationFrame(tick);
  }, []);

  const start = useCallback(() => {
    if (running.current) return;
    running.current = true;
    finishing.current = false;
    raf.current = requestAnimationFrame(tick);
  }, [tick]);

  /** Feed raw text from the transport. */
  const push = useCallback(
    (text: string) => {
      if (!text) return;
      buffer.current += text;
      start();
    },
    [start],
  );

  /** Transport closed: drain what's left, then stop the loop. */
  const finish = useCallback(() => {
    finishing.current = true;
    if (!running.current && buffer.current.length) start();
  }, [start]);

  /** Abort: hand back the undrained remainder so the caller can commit it. */
  const flushNow = useCallback(() => {
    const rest = buffer.current;
    buffer.current = "";
    finishing.current = false;
    running.current = false;
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = null;
    return rest;
  }, []);

  const pending = useCallback(() => buffer.current.length, []);

  useEffect(
    () => () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    },
    [],
  );

  return { push, finish, flushNow, pending };
}
