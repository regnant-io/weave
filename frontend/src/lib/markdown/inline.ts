/**
 * Inline markdown tokenizer.
 *
 * Hand-written on purpose. The previous stack (react-markdown + remark-gfm)
 * pulled in `mdast-util-gfm-autolink-literal`, which ships a regex LOOKBEHIND
 * (`/(?<=^|\s|\p{P}|\p{S})…/u`). Lookbehind is a *parse-time* SyntaxError on
 * Safari below 16.4, so the whole JS chunk failed to evaluate and the app died
 * outright on iOS 15 — no error boundary can catch that. Nothing in this file
 * uses a construct newer than ES2017.
 *
 * It is also a single left-to-right scan with no intermediate AST libraries,
 * which is what makes per-token streaming cost flat instead of quadratic.
 */

export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "del"; c: Inline[] }
  | { t: "link"; href: string; title?: string; c: Inline[] }
  | { t: "img"; src: string; alt: string; title?: string }
  | { t: "br" };

const PUNCT = new Set([
  "\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-",
  ".", "!", "|", ">", "~", "<", '"', "'", "$",
]);

const isSpace = (ch: string | undefined) => ch === undefined || /\s/.test(ch);
const isPunctChar = (ch: string | undefined) =>
  ch !== undefined && /[!-/:-@[-`{-~]/.test(ch);

/** Count the run of `ch` starting at `i`. */
function runLength(src: string, i: number, ch: string): number {
  let n = 0;
  while (i + n < src.length && src[i + n] === ch) n++;
  return n;
}

/**
 * Find the index of the closing `]` matching an opening `[` at `open`,
 * honouring nesting and escapes. Returns -1 when unclosed (streaming case).
 */
function matchBracket(src: string, open: number): number {
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (c === "\\") {
      i++;
      continue;
    }
    if (c === "`") {
      // Skip code spans — brackets inside them are literal.
      const n = runLength(src, i, "`");
      const close = src.indexOf("`".repeat(n), i + n);
      if (close === -1) return -1;
      i = close + n - 1;
      continue;
    }
    if (c === "[") depth++;
    else if (c === "]") {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/** Parse `(href "title")` starting at `i` (which must point at `(`). */
function parseDestination(
  src: string,
  i: number,
): { href: string; title?: string; end: number } | null {
  if (src[i] !== "(") return null;
  let depth = 0;
  let j = i;
  for (; j < src.length; j++) {
    const c = src[j];
    if (c === "\\") {
      j++;
      continue;
    }
    if (c === "(") depth++;
    else if (c === ")") {
      depth--;
      if (depth === 0) break;
    }
  }
  if (j >= src.length) return null; // unterminated — still streaming
  const raw = src.slice(i + 1, j).trim();
  // Split off an optional quoted title.
  const m = /^(<[^>]*>|\S*?)(?:\s+["'(]([\s\S]*)["')])?$/.exec(raw);
  if (!m) return { href: raw, end: j + 1 };
  let href = m[1] ?? "";
  if (href.startsWith("<") && href.endsWith(">")) href = href.slice(1, -1);
  return { href, title: m[2], end: j + 1 };
}

const SCHEMES = ["https://", "http://", "mailto:"];

/** Length of a bare URL starting at `i`, or 0. Trailing punctuation is excluded. */
function bareUrlLength(src: string, i: number): number {
  let matched = "";
  for (const s of SCHEMES) {
    if (src.startsWith(s, i)) {
      matched = s;
      break;
    }
  }
  if (!matched && src.startsWith("www.", i)) matched = "www.";
  if (!matched) return 0;
  // A URL may not start mid-word (no lookbehind needed — we have the index).
  const prev = i > 0 ? src[i - 1] : undefined;
  if (prev !== undefined && /[A-Za-z0-9]/.test(prev)) return 0;

  let j = i + matched.length;
  while (j < src.length && !/[\s<>"'`]/.test(src[j])) j++;
  // Don't swallow sentence-final punctuation or a closing bracket that belongs
  // to the surrounding text.
  while (j > i && /[.,;:!?)\]}'"]/.test(src[j - 1])) {
    if (src[j - 1] === ")") {
      // Keep a balanced ")" (common in wiki URLs).
      const slice = src.slice(i, j);
      const opens = (slice.match(/\(/g) || []).length;
      const closes = (slice.match(/\)/g) || []).length;
      if (opens >= closes) break;
    }
    j--;
  }
  return j - i > matched.length ? j - i : 0;
}

/**
 * Find the closing delimiter run for emphasis opened at `start` with `len`
 * copies of `ch`. Skips code spans and escapes. Returns -1 when unclosed.
 */
function findEmphasisClose(src: string, start: number, ch: string, len: number): number {
  for (let i = start; i < src.length; i++) {
    const c = src[i];
    if (c === "\\") {
      i++;
      continue;
    }
    if (c === "`") {
      const n = runLength(src, i, "`");
      const close = src.indexOf("`".repeat(n), i + n);
      if (close === -1) return -1;
      i = close + n - 1;
      continue;
    }
    if (c !== ch) continue;
    const run = runLength(src, i, ch);
    if (run < len) {
      i += run - 1;
      continue;
    }
    // Right-flanking: must not be preceded by whitespace.
    if (isSpace(src[i - 1])) {
      i += run - 1;
      continue;
    }
    // Intraword `_` is not emphasis (snake_case must survive).
    if (ch === "_") {
      const after = src[i + run];
      if (after !== undefined && /[A-Za-z0-9]/.test(after)) {
        i += run - 1;
        continue;
      }
    }
    return i;
  }
  return -1;
}

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let buf = "";
  let i = 0;

  const flush = () => {
    if (buf) {
      out.push({ t: "text", v: buf });
      buf = "";
    }
  };

  while (i < src.length) {
    const c = src[i];

    // --- escapes ---------------------------------------------------------
    if (c === "\\") {
      const next = src[i + 1];
      if (next === "\n") {
        flush();
        out.push({ t: "br" });
        i += 2;
        continue;
      }
      if (next !== undefined && PUNCT.has(next)) {
        buf += next;
        i += 2;
        continue;
      }
      buf += c;
      i++;
      continue;
    }

    // --- hard line break (two trailing spaces) ---------------------------
    if (c === "\n") {
      if (buf.endsWith("  ")) {
        buf = buf.replace(/ +$/, "");
        flush();
        out.push({ t: "br" });
      } else {
        buf += " ";
      }
      i++;
      continue;
    }

    // --- code span (literal: wins over everything) -----------------------
    if (c === "`") {
      const n = runLength(src, i, "`");
      const fence = "`".repeat(n);
      const close = src.indexOf(fence, i + n);
      if (close !== -1) {
        let content = src.slice(i + n, close);
        // CommonMark: strip one leading+trailing space if both present.
        if (content.length > 2 && content.startsWith(" ") && content.endsWith(" ")) {
          content = content.slice(1, -1);
        }
        flush();
        out.push({ t: "code", v: content });
        i = close + n;
        continue;
      }
      buf += fence;
      i += n;
      continue;
    }

    // --- image -----------------------------------------------------------
    if (c === "!" && src[i + 1] === "[") {
      const close = matchBracket(src, i + 1);
      if (close !== -1) {
        const dest = parseDestination(src, close + 1);
        if (dest) {
          flush();
          out.push({
            t: "img",
            alt: src.slice(i + 2, close),
            src: dest.href,
            title: dest.title,
          });
          i = dest.end;
          continue;
        }
      }
      buf += c;
      i++;
      continue;
    }

    // --- link ------------------------------------------------------------
    if (c === "[") {
      const close = matchBracket(src, i);
      if (close !== -1) {
        const dest = parseDestination(src, close + 1);
        if (dest) {
          flush();
          out.push({
            t: "link",
            href: dest.href,
            title: dest.title,
            c: parseInline(src.slice(i + 1, close)),
          });
          i = dest.end;
          continue;
        }
      }
      buf += c;
      i++;
      continue;
    }

    // --- autolink <https://…> --------------------------------------------
    if (c === "<") {
      const close = src.indexOf(">", i + 1);
      if (close !== -1) {
        const inner = src.slice(i + 1, close);
        if (/^(https?:\/\/|mailto:)\S+$/.test(inner)) {
          flush();
          out.push({ t: "link", href: inner, c: [{ t: "text", v: inner }] });
          i = close + 1;
          continue;
        }
        if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(inner)) {
          flush();
          out.push({ t: "link", href: `mailto:${inner}`, c: [{ t: "text", v: inner }] });
          i = close + 1;
          continue;
        }
      }
      buf += c;
      i++;
      continue;
    }

    // --- bare URL --------------------------------------------------------
    if (c === "h" || c === "w" || c === "m") {
      const len = bareUrlLength(src, i);
      if (len > 0) {
        const url = src.slice(i, i + len);
        flush();
        out.push({
          t: "link",
          href: url.startsWith("www.") ? `https://${url}` : url,
          c: [{ t: "text", v: url }],
        });
        i += len;
        continue;
      }
    }

    // --- strikethrough ---------------------------------------------------
    if (c === "~" && src[i + 1] === "~") {
      const close = findEmphasisClose(src, i + 2, "~", 2);
      if (close !== -1) {
        flush();
        out.push({ t: "del", c: parseInline(src.slice(i + 2, close)) });
        i = close + 2;
        continue;
      }
      buf += "~~";
      i += 2;
      continue;
    }

    // --- emphasis --------------------------------------------------------
    if (c === "*" || c === "_") {
      const run = runLength(src, i, c);
      const after = src[i + run];
      const leftFlanking = !isSpace(after) && after !== undefined;
      // Intraword `_` must not open emphasis.
      const intraword =
        c === "_" && i > 0 && /[A-Za-z0-9]/.test(src[i - 1]) && !isPunctChar(src[i - 1]);
      if (leftFlanking && !intraword) {
        const len = run >= 2 ? 2 : 1;
        const close = findEmphasisClose(src, i + run, c, len);
        if (close !== -1) {
          const inner = parseInline(src.slice(i + run, close));
          flush();
          // `***x***` -> strong wrapping em.
          if (run >= 3) out.push({ t: "strong", c: [{ t: "em", c: inner }] });
          else if (len === 2) out.push({ t: "strong", c: inner });
          else out.push({ t: "em", c: inner });
          i = close + len;
          continue;
        }
      }
      buf += c.repeat(run);
      i += run;
      continue;
    }

    buf += c;
    i++;
  }

  flush();
  return out;
}
