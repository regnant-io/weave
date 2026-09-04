/**
 * Block-level markdown parser (CommonMark subset + GFM tables, task lists,
 * strikethrough), written to be safe on old Safari and cheap enough to run on
 * every streamed token.
 *
 * Streaming is a first-class concern: an unterminated fence, table or list is a
 * normal intermediate state, not an error, so every construct has a defined
 * partial rendering. `open: true` on a code block means "the fence has not been
 * closed yet" so the UI can avoid animating a block that is still growing.
 */

export type Align = "left" | "center" | "right" | null;

export type Blk =
  | { t: "h"; level: number; text: string }
  | { t: "p"; text: string }
  | { t: "code"; lang: string; code: string; open: boolean }
  | { t: "hr" }
  | { t: "quote"; children: Blk[] }
  | { t: "list"; ordered: boolean; start: number; items: ListItem[] }
  | { t: "table"; head: string[]; align: Align[]; rows: string[][] };

export interface ListItem {
  /** undefined = not a task item; true/false = checked state. */
  checked?: boolean;
  children: Blk[];
}

const FENCE_RE = /^(\s*)(`{3,}|~{3,})\s*([^`\s]*)/;
const ATX_RE = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR_RE = /^ {0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$/;
const UL_RE = /^(\s*)([-*+])\s+(.*)$/;
const OL_RE = /^(\s*)(\d{1,9})[.)]\s+(.*)$/;
const QUOTE_RE = /^ {0,3}>\s?(.*)$/;
const TASK_RE = /^\[([ xX])\]\s+(.*)$/;
const SETEXT_RE = /^ {0,3}(=+|-+)\s*$/;

/** Is this line the `|---|:--:|` separator of a GFM table? */
function tableAlign(line: string): Align[] | null {
  const trimmed = line.trim();
  if (!trimmed.includes("-")) return null;
  const body = trimmed.replace(/^\|/, "").replace(/\|$/, "");
  const cells = body.split("|");
  if (!cells.length) return null;
  const out: Align[] = [];
  for (const raw of cells) {
    const c = raw.trim();
    if (!/^:?-+:?$/.test(c)) return null;
    const left = c.startsWith(":");
    const right = c.endsWith(":");
    out.push(left && right ? "center" : right ? "right" : left ? "left" : null);
  }
  return out;
}

/** Split a table row on unescaped pipes. */
function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  const cells: string[] = [];
  let cur = "";
  for (let i = 0; i < trimmed.length; i++) {
    const c = trimmed[i];
    if (c === "\\" && trimmed[i + 1] === "|") {
      cur += "|";
      i++;
      continue;
    }
    if (c === "|") {
      cells.push(cur.trim());
      cur = "";
      continue;
    }
    cur += c;
  }
  cells.push(cur.trim());
  return cells;
}

const indentOf = (s: string) => (s.match(/^\s*/)?.[0].length ?? 0);

export function parseBlocks(src: string): Blk[] {
  return parseLines(src.replace(/\r\n?/g, "\n").split("\n"));
}

function parseLines(lines: string[]): Blk[] {
  const out: Blk[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i++;
      continue;
    }

    // --- fenced code -----------------------------------------------------
    const fence = FENCE_RE.exec(line);
    if (fence) {
      const marker = fence[2][0];
      const width = fence[2].length;
      const baseIndent = fence[1].length;
      const lang = (fence[3] || "").trim();
      const body: string[] = [];
      i++;
      let closed = false;
      while (i < lines.length) {
        const l = lines[i];
        const closeRe = new RegExp(`^\\s*${marker === "`" ? "`" : "~"}{${width},}\\s*$`);
        if (closeRe.test(l)) {
          closed = true;
          i++;
          break;
        }
        // Strip the fence's own indentation from each content line.
        body.push(l.slice(0, baseIndent).trim() === "" ? l.slice(baseIndent) : l);
        i++;
      }
      out.push({ t: "code", lang, code: body.join("\n"), open: !closed });
      continue;
    }

    // --- ATX heading -----------------------------------------------------
    const atx = ATX_RE.exec(line);
    if (atx) {
      out.push({ t: "h", level: atx[1].length, text: atx[2] });
      i++;
      continue;
    }

    // --- thematic break --------------------------------------------------
    if (HR_RE.test(line)) {
      out.push({ t: "hr" });
      i++;
      continue;
    }

    // --- blockquote ------------------------------------------------------
    if (QUOTE_RE.test(line)) {
      const inner: string[] = [];
      while (i < lines.length) {
        const m = QUOTE_RE.exec(lines[i]);
        if (m) {
          inner.push(m[1]);
          i++;
          continue;
        }
        // Lazy continuation: a plain line directly after a quote line.
        if (lines[i].trim() !== "" && !FENCE_RE.test(lines[i]) && !ATX_RE.test(lines[i])) {
          inner.push(lines[i]);
          i++;
          continue;
        }
        break;
      }
      out.push({ t: "quote", children: parseLines(inner) });
      continue;
    }

    // --- table -----------------------------------------------------------
    if (line.includes("|") && i + 1 < lines.length) {
      const align = tableAlign(lines[i + 1]);
      if (align) {
        const head = splitRow(line);
        if (head.length === align.length) {
          i += 2;
          const rows: string[][] = [];
          while (i < lines.length && lines[i].trim() !== "" && lines[i].includes("|")) {
            const cells = splitRow(lines[i]);
            // Pad/trim to the header width so the grid never goes ragged.
            while (cells.length < head.length) cells.push("");
            rows.push(cells.slice(0, head.length));
            i++;
          }
          out.push({ t: "table", head, align, rows });
          continue;
        }
      }
    }

    // --- list ------------------------------------------------------------
    const ul = UL_RE.exec(line);
    const ol = OL_RE.exec(line);
    if (ul || ol) {
      const ordered = Boolean(ol);
      const marker = ul ?? ol!;
      const baseIndent = marker[1].length;
      const start = ordered ? parseInt(ol![2], 10) : 1;
      const items: ListItem[] = [];
      let itemLines: string[] = [];
      let checked: boolean | undefined;

      const commit = () => {
        if (!itemLines.length && checked === undefined) return;
        items.push({ checked, children: parseLines(itemLines) });
        itemLines = [];
        checked = undefined;
      };

      while (i < lines.length) {
        const l = lines[i];
        if (l.trim() === "") {
          // A blank line only ends the list if the next content line is not a
          // continuation — loose lists must stay one list.
          let j = i + 1;
          while (j < lines.length && lines[j].trim() === "") j++;
          if (j >= lines.length) break;
          const nextIndent = indentOf(lines[j]);
          const nextIsItem = UL_RE.test(lines[j]) || OL_RE.test(lines[j]);
          if (!(nextIsItem && nextIndent === baseIndent) && nextIndent <= baseIndent) break;
          itemLines.push("");
          i++;
          continue;
        }

        const mUl = UL_RE.exec(l);
        const mOl = OL_RE.exec(l);
        const m = mUl ?? mOl;
        const sameKind = Boolean(mUl) === !ordered;

        if (m && m[1].length === baseIndent && sameKind) {
          commit();
          const content = ordered ? mOl![3] : mUl![3];
          const task = TASK_RE.exec(content);
          if (task) {
            checked = task[1].toLowerCase() === "x";
            itemLines.push(task[2]);
          } else {
            itemLines.push(content);
          }
          i++;
          continue;
        }
        if (m && m[1].length === baseIndent && !sameKind) break; // different list type
        if (indentOf(l) > baseIndent) {
          // Continuation / nested block: strip one level of indentation.
          itemLines.push(l.slice(Math.min(indentOf(l), baseIndent + 2)));
          i++;
          continue;
        }
        if (items.length === 0 && itemLines.length === 0) break;
        // Lazy paragraph continuation inside the current item.
        if (!HR_RE.test(l) && !ATX_RE.test(l) && !FENCE_RE.test(l)) {
          itemLines.push(l);
          i++;
          continue;
        }
        break;
      }
      commit();
      out.push({ t: "list", ordered, start, items });
      continue;
    }

    // --- paragraph (with setext heading support) -------------------------
    const para: string[] = [];
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === "") break;
      if (para.length && (ATX_RE.test(l) || HR_RE.test(l) || FENCE_RE.test(l) || QUOTE_RE.test(l)))
        break;
      if (para.length && (UL_RE.test(l) || OL_RE.test(l))) break;
      const setext = para.length ? SETEXT_RE.exec(l) : null;
      if (setext && !HR_RE.test(l)) {
        out.push({ t: "h", level: setext[1][0] === "=" ? 1 : 2, text: para.join(" ") });
        i++;
        para.length = 0;
        break;
      }
      para.push(l);
      i++;
    }
    if (para.length) out.push({ t: "p", text: para.join("\n") });
  }

  return out;
}

/**
 * Split a document into independently-renderable top-level segments.
 *
 * Only the LAST segment can change while streaming, so every earlier one keeps
 * its identity and React skips it entirely. Splitting naively on blank lines
 * would tear a loose list or a fenced block in half, so the boundary check is
 * construct-aware.
 */
export function splitSegments(text: string): string[] {
  return splitSegmentsFrom(text).segments;
}

/**
 * The same split, but reporting where the LAST segment begins.
 *
 * That offset is what makes re-splitting incremental. While an answer streams,
 * this function is called on every frame with a string that is only ever longer
 * at the end — and re-scanning the whole document each time is work proportional
 * to the answer so far, sixty times a second. On a short reply that is
 * invisible; on a long one, on the mid-range Android this product is built for,
 * it is the difference between text that flows and text that hitches.
 *
 * Appending can only affect the final segment, because a boundary is a blank
 * line (or a fence close) that has already been seen. So a caller holding the
 * previous result can re-split `text.slice(lastStart)` and concatenate — see
 * `Markdown.tsx`.
 */
export function splitSegmentsFrom(text: string): { segments: string[]; lastStart: number } {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const segments: string[] = [];
  //: Character offset of the first line of the segment being accumulated.
  const starts: number[] = [];
  let curStart = 0;
  let offset = 0;
  let cur: string[] = [];
  let fence: string | null = null;

  const flush = () => {
    if (cur.length) {
      segments.push(cur.join("\n"));
      starts.push(curStart);
      cur = [];
    }
  };
  //: Record where a segment starts, the first time a line lands in it.
  const take = (line: string) => {
    if (!cur.length) curStart = offset;
    cur.push(line);
    offset += line.length + 1; // +1 for the newline `split` removed
  };
  //: A line that opens no segment still advances the cursor. Without this every
  //: blank line would shift every later segment's recorded start.
  const skip = (line: string) => {
    offset += line.length + 1;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (fence) {
      take(line);
      if (new RegExp(`^\\s*${fence}`).test(line)) fence = null;
      continue;
    }
    const f = FENCE_RE.exec(line);
    if (f) {
      take(line);
      fence = f[2][0] === "`" ? "`{3,}" : "~{3,}";
      continue;
    }

    if (line.trim() === "") {
      // Peek at the next content line: if it continues the current construct,
      // the blank line is interior, not a boundary.
      let j = i + 1;
      while (j < lines.length && lines[j].trim() === "") j++;
      if (j >= lines.length) {
        flush();
        skip(line);
        continue;
      }
      const next = lines[j];
      const curStartsList = cur.length > 0 && (UL_RE.test(cur[0]) || OL_RE.test(cur[0]));
      const nextIsList = UL_RE.test(next) || OL_RE.test(next);
      const nextIndented = indentOf(next) >= 2;
      const curIsQuote = cur.length > 0 && QUOTE_RE.test(cur[0]);
      const nextIsQuote = QUOTE_RE.test(next);

      if ((curStartsList && (nextIsList || nextIndented)) || (curIsQuote && nextIsQuote)) {
        cur.push("");
        skip(line);
        continue;
      }
      flush();
      skip(line);
      continue;
    }

    take(line);
  }
  flush();
  return {
    segments,
    lastStart: starts.length ? starts[starts.length - 1] : 0,
  };
}
