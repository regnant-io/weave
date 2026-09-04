"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * Rate-smoothed token drain.
 *
 * Raw SSE arrives in lumps: the network coalesces frames, and a local Ollama
 * emits a whole word — sometimes a whole sentence — per message. Flushing
 * whatever landed once per frame reproduces that lumpiness exactly, so text
 * arrives in visible chunks with dead frames between them.
 *
 * Arriving text is treated as a reservoir and released at a controlled rate, so
 * the reader sees continuous flow regardless of how bursty the source is.
 *
 * Three properties make it read as smooth rather than merely fast:
 *
 *  1. TIME-BASED, not frame-based. The previous version released
 *     `pending / (140ms / 16.67ms)` characters per frame, which silently
 *     assumed 60Hz. On a 120Hz iPad that drained twice as fast as intended, and
 *     on a struggling low-end Android it stalled. Here the release is
 *     `rate × elapsed`, measured from the real clock, so the perceived speed is
 *     identical on every device.
 *
 *  2. The rate is EASED, not recomputed. A burst arriving mid-sentence would
 *     otherwise cause an instant speed-up that reads as a stutter; an
 *     exponential moving average lets the rate accelerate over a few frames
 *     instead of stepping.
 *
 *  3. Releases land on WORD boundaries, so words never visibly assemble letter
 *     by letter — which reads as glitchy rather than fluid.
 *
 * There is deliberately no caret. Growth is the only motion cue.
 */

/** Aim to have emptied whatever is buffered within roughly this long. */
const DRAIN_TARGET_MS = 130;
/** Land the tail within this long once the transport has closed. */
const FINISH_TARGET_MS = 220;
/** Backlog past this means the model is far ahead; shorten the target. */
const FLOOD_CHARS = 700;
/** The most the flood response may compress the drain target. */
const MAX_FLOOD_COMPRESSION = 3;
/** Chars/ms. ~0.02 is a readable trickle; without a floor a slow model freezes. */
const MIN_RATE = 0.02;
/** Chars/ms ceiling, so a huge paste still reads as fast typing, not a jump. */
const MAX_RATE = 3.5;
/** EMA weight for new rate observations. Lower = smoother, slower to react. */
const RATE_SMOOTHING = 0.18;
/** Never spend longer than this hunting for a word boundary. */
const BOUNDARY_LOOKAHEAD = 16;
/** Stop the idle loop after this long with nothing to drain. */
const IDLE_TIMEOUT_MS = 1500;

export function useSmoothStream(onChars: (chunk: string) => void) {
  const buffer = useRef("");
  const raf = useRef<number | null>(null);
  const running = useRef(false);
  const finishing = useRef(false);
  const rate = useRef(0); // chars per millisecond
  const lastTs = useRef(0);
  const carry = useRef(0); // sub-character remainder, so slow rates still advance
  const idleSince = useRef(0); // when the buffer last ran dry, for the idle timeout
  const onCharsRef = useRef(onChars);
  onCharsRef.current = onChars;

  const stop = useCallback(() => {
    running.current = false;
    finishing.current = false;
    if (raf.current !== null) cancelAnimationFrame(raf.current);
    raf.current = null;
    rate.current = 0;
    carry.current = 0;
    idleSince.current = 0;
  }, []);

  const tick = useCallback((ts: number) => {
    const pending = buffer.current.length;

    if (pending === 0) {
      if (finishing.current) {
        stop();
        return;
      }
      /*
        Idle but still connected.

        The loop is kept alive briefly so the first frame after a short gap
        between tool calls does not release a burst - but only briefly. The
        previous version span a requestAnimationFrame forever for the whole
        turn, waking the main thread sixty times a second through every pause,
        every tool call and every minute of a long agentic run, to discover
        that there was nothing to do. `push` restarts it, so stopping costs
        nothing but the clock reset, which `start` performs anyway.
      */
      if (!idleSince.current) idleSince.current = ts;
      else if (ts - idleSince.current > IDLE_TIMEOUT_MS) {
        stop();
        return;
      }
      lastTs.current = ts;
      rate.current = 0;
      raf.current = requestAnimationFrame(tick);
      return;
    }
    idleSince.current = 0;

    const elapsed = lastTs.current ? Math.min(64, ts - lastTs.current) : 16;
    lastTs.current = ts;

    /*
      Target rate empties the reservoir within the window we are aiming for.

      The flood response used to be a STEP: below 700 buffered characters the
      target was 130ms, at 701 it became 43ms. Crossing that line mid-sentence -
      which happens constantly, because a model emits in bursts - tripled the
      release rate between one frame and the next, and a threefold speed change
      inside a word is exactly the lurch the smoother exists to remove. Scaling
      continuously past the same threshold reaches the same maximum urgency
      without a discontinuity anywhere.
    */
    let target = DRAIN_TARGET_MS;
    if (finishing.current) {
      target = FINISH_TARGET_MS;
    } else if (pending > FLOOD_CHARS) {
      const compression = Math.min(MAX_FLOOD_COMPRESSION, pending / FLOOD_CHARS);
      target = DRAIN_TARGET_MS / compression;
    }
    const observed = Math.min(MAX_RATE, Math.max(MIN_RATE, pending / target));

    // Ease toward the observed rate rather than snapping to it.
    rate.current = rate.current
      ? rate.current + (observed - rate.current) * RATE_SMOOTHING
      : observed;

    const exact = rate.current * elapsed + carry.current;
    let n = Math.floor(exact);
    carry.current = exact - n;
    if (n < 1) {
      raf.current = requestAnimationFrame(tick);
      return;
    }
    if (n > pending) n = pending;

    // Snap forward to the next whitespace so a word is never half-revealed.
    if (n < pending) {
      const budget = n;
      const window = buffer.current.slice(n, Math.min(pending, n + BOUNDARY_LOOKAHEAD));
      const ws = window.search(/\s/);
      if (ws >= 0) n += ws + 1;
      else if (pending - n <= BOUNDARY_LOOKAHEAD) n = pending; // short tail: take it all
      /*
        Charge the overshoot back.

        Snapping forward hands out characters this frame's budget had not
        earned. Taking them for free meant every long word was a small
        acceleration, so the perceived speed rose and fell with the vocabulary -
        technical prose visibly ran faster than plain prose. Recording the
        excess as negative carry makes the next frames release proportionally
        less, so the AVERAGE rate is exactly what was asked for and the cadence
        is even regardless of word length.
      */
      carry.current -= n - budget;
    }

    const chunk = buffer.current.slice(0, n);
    buffer.current = buffer.current.slice(n);
    onCharsRef.current(chunk);

    raf.current = requestAnimationFrame(tick);
  }, [stop]);

  const start = useCallback(() => {
    if (running.current) return;
    running.current = true;
    finishing.current = false;
    lastTs.current = 0;
    carry.current = 0;
    idleSince.current = 0;
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

  /** Transport closed: drain what's left promptly, then stop the loop. */
  const finish = useCallback(() => {
    finishing.current = true;
    if (!running.current && buffer.current.length) {
      running.current = true;
      lastTs.current = 0;
      idleSince.current = 0;
      raf.current = requestAnimationFrame(tick);
    }
  }, [tick]);

  /** Abort: hand back the undrained remainder so the caller can commit it. */
  const flushNow = useCallback(() => {
    const rest = buffer.current;
    buffer.current = "";
    stop();
    return rest;
  }, [stop]);

  const pending = useCallback(() => buffer.current.length, []);

  /**
   * Discard everything undrained without committing it.
   *
   * Distinct from `flushNow`, which hands the remainder back so the caller can
   * keep it. This is for the case where the buffered text should never appear:
   * the user redirected the turn mid-stream, so the tokens still in flight
   * belong to reasoning that has been overridden. Committing them would leave
   * the answer contradicting its own opening.
   */
  const reset = useCallback(() => {
    buffer.current = "";
    finishing.current = false;
    stop();
  }, [stop]);

  useEffect(() => () => stop(), [stop]);

  return { push, finish, flushNow, pending, reset };
}
