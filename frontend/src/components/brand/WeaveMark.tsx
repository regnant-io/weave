"use client";

/**
 * The Weave wordmark — drawn, not typed.
 *
 * One continuous monoline stroke. The trace enters flat at cap height like an
 * idle heart monitor, plunges into the W (which is naturally a QRS burst),
 * flows through "eave" as unbroken cursive, and settles onto a flat baseline
 * that runs off the right edge.
 *
 * The lead-in sits at CAP height on purpose: entering at the baseline forces an
 * upstroke into the W's first apex, and that phantom stroke makes the mark read
 * "Meave". Entering level with the first apex removes it entirely.
 *
 * `pathLength={1}` normalises the dash maths so the draw is resolution-
 * independent, and the same `d` feeds the pulse's CSS `offset-path`, so the dot
 * is always exactly on the ink.
 */

// Geometry: baseline y=130, x-height y=86, cap y=38.
//
// The W is the whole problem. Every earlier attempt read "Meave", and the cause
// was always the same: m/n are round on TOP with sharp joins at the baseline,
// while w is the inverse — diagonal strokes meeting in softly rounded V's with
// SHARP apexes. Round both ends and the letter is genuinely ambiguous. A flat
// lead-in stroke before the W is equally fatal: it adds a phantom stem the eye
// reads as M's first leg, so the trace only joins on the exit side.
export const WEAVE_PATH =
  // W — diagonals with tight rounded-V joins; middle apex dropped, as in script
  "M 52 38 " +
  "C 70 78 92 118 100 130 " +
  "C 108 118 130 80 150 50 " +
  "C 170 80 192 118 200 130 " +
  "C 208 118 228 78 246 38 " +
  // e — fall out of the W, rising crossbar, loop over the top, out along the base
  "C 250 58 252 76 257 90 " +
  "C 265 103 281 105 291 95 " +
  "C 301 85 295 74 283 78 " +
  "C 269 83 263 102 269 116 " +
  "C 277 128 296 128 306 118 " +
  // a — counter-clockwise bowl closed with a right-hand stem
  "C 316 108 326 89 342 89 " +
  "C 357 89 364 104 360 117 " +
  "C 355 129 337 131 333 119 " +
  "C 329 105 341 95 355 99 " +
  "C 361 102 361 115 363 125 " +
  "C 366 131 374 130 379 122 " +
  // v — rise, rounded trough, rise, small exit hook
  "C 385 110 389 96 394 87 " +
  "C 400 105 407 126 417 128 " +
  "C 428 130 434 104 438 85 " +
  "C 440 78 445 79 448 85 " +
  // e
  "C 453 97 456 107 462 115 " +
  "C 470 125 486 127 496 117 " +
  "C 506 107 500 95 488 99 " +
  "C 474 104 468 121 474 131 " +
  "C 481 138 497 137 508 129 " +
  // settle onto the trailing trace and run off the edge
  "C 524 132 542 130 566 130 L 900 130";

/** Italic slant, in degrees. Horizontal lines stay horizontal under skewX. */
const SLANT = -9;

/** Cropped box for lockups where the long trailing trace would be dead space. */
const VB_TIGHT = "24 16 620 144";
const VB_FULL = "8 10 934 168";

const SIZES = {
  xs: { vb: VB_TIGHT, w: 92, h: 21, sw: 11 },
  sm: { vb: VB_TIGHT, w: 118, h: 27, sw: 10 },
  md: { vb: VB_TIGHT, w: 158, h: 37, sw: 9 },
  lg: { vb: VB_FULL, w: 340, h: 61, sw: 7 },
  hero: { vb: VB_FULL, w: 560, h: 101, sw: 6 },
} as const;

export type WeaveMarkSize = keyof typeof SIZES;

export default function WeaveMark({
  size = "md",
  animate = true,
  pulse = true,
  loop = false,
  duration = 2400,
  delay = 0,
  className = "",
  title = "Weave",
}: {
  size?: WeaveMarkSize;
  /** Draw the stroke on mount. When false, renders complete. */
  animate?: boolean;
  /** Ride a glowing dot along the trace while it draws. */
  pulse?: boolean;
  /** Redraw forever — the monitor-running loading state. */
  loop?: boolean;
  duration?: number;
  delay?: number;
  className?: string;
  title?: string;
}) {
  const { vb, w, h, sw } = SIZES[size];
  const iter = loop ? "infinite" : "1";
  const fill = loop ? "none" : "forwards";

  return (
    <svg
      viewBox={vb}
      width={w}
      height={h}
      role="img"
      aria-label={title}
      className={`overflow-visible ${className}`}
      style={
        {
          "--wm-dur": `${duration}ms`,
          "--wm-delay": `${delay}ms`,
          "--wm-iter": iter,
          "--wm-fill": fill,
        } as React.CSSProperties
      }
    >
      <title>{title}</title>

      {/* The slant lives on a group so the pulse inherits it and stays exactly
          on the ink — offset-path is resolved in the element's own coordinate
          system, which is the skewed one here. */}
      <g transform={`skewX(${SLANT})`}>
        <path
          d={WEAVE_PATH}
          pathLength={1}
          fill="none"
          stroke="currentColor"
          strokeWidth={sw}
          strokeLinecap="round"
          strokeLinejoin="round"
          className={animate ? "wm-draw" : undefined}
        />

        {animate && pulse && (
          <circle
            r={sw * 1.35}
            fill="var(--accent)"
            className="wm-pulse"
            style={{ offsetPath: `path("${WEAVE_PATH}")` } as React.CSSProperties}
          />
        )}
      </g>

      <style>{`
        .wm-draw {
          stroke-dasharray: 1 1;
          stroke-dashoffset: 1;
          animation: wmDraw var(--wm-dur) cubic-bezier(.65,0,.35,1) var(--wm-delay)
            var(--wm-iter) var(--wm-fill);
        }
        @keyframes wmDraw { to { stroke-dashoffset: 0; } }

        .wm-pulse {
          offset-rotate: 0deg;
          offset-distance: 0%;
          opacity: 0;
          filter: drop-shadow(0 0 5px var(--accent-glow));
          animation:
            wmRide var(--wm-dur) cubic-bezier(.65,0,.35,1) var(--wm-delay) var(--wm-iter) var(--wm-fill),
            wmFlare var(--wm-dur) linear var(--wm-delay) var(--wm-iter) var(--wm-fill);
        }
        @keyframes wmRide { to { offset-distance: 100%; } }
        @keyframes wmFlare {
          0%   { opacity: 0; }
          5%   { opacity: 1; }
          90%  { opacity: 1; }
          100% { opacity: 0; }
        }

        @media (prefers-reduced-motion: reduce) {
          .wm-draw { stroke-dashoffset: 0; animation: none; }
          .wm-pulse { display: none; }
        }
      `}</style>
    </svg>
  );
}
