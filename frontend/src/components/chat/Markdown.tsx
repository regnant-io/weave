"use client";

import { memo, useMemo, useState } from "react";
import type { Artifact } from "@/lib/types";
import { parseBlocks, splitSegments, type Align, type Blk } from "@/lib/markdown/blocks";
import { parseInline, type Inline } from "@/lib/markdown/inline";
import { IcoCheck, IcoCopy } from "@/components/ui/icons";

/**
 * Streaming markdown.
 *
 * Two properties matter here and they pull in the same direction:
 *
 *  1. It must PARSE on iOS 15. The previous renderer (react-markdown +
 *     remark-gfm) shipped a regex lookbehind that is a SyntaxError on Safari
 *     < 16.4, taking the entire chunk — and therefore the whole app — down.
 *  2. Per-token cost must be FLAT. react-markdown rebuilt a full mdast → hast →
 *     React tree for the whole answer on every token, so a long answer got
 *     visibly slower the longer it ran. Here the document is split into
 *     segments; every finished segment is memoised and never re-parses, so only
 *     the small growing tail does any work per frame.
 */

/* --------------------------------------------------------------- inline */

function renderInline(nodes: Inline[], onOpenArtifact?: (a: Artifact) => void): React.ReactNode {
  return nodes.map((n, i) => {
    switch (n.t) {
      case "text":
        return <span key={i}>{n.v}</span>;
      case "br":
        return <br key={i} />;
      case "code":
        return <code key={i}>{n.v}</code>;
      case "strong":
        return <strong key={i}>{renderInline(n.c, onOpenArtifact)}</strong>;
      case "em":
        return <em key={i}>{renderInline(n.c, onOpenArtifact)}</em>;
      case "del":
        return <del key={i}>{renderInline(n.c, onOpenArtifact)}</del>;
      case "img":
        return <InlineImage key={i} src={n.src} alt={n.alt} onOpen={onOpenArtifact} />;
      case "link": {
        const isArtifact = n.href.startsWith("/api/artifact/");
        if (isArtifact && onOpenArtifact) {
          return (
            <button
              key={i}
              type="button"
              onClick={() =>
                onOpenArtifact({
                  name: flattenText(n.c) || "Artifact",
                  mime: guessMime(n.href),
                  bytes: 0,
                  url: n.href,
                })
              }
              className="text-accent underline decoration-accent-line underline-offset-2 transition-colors duration-fast hover:decoration-accent"
            >
              {renderInline(n.c, onOpenArtifact)}
            </button>
          );
        }
        return (
          <a key={i} href={n.href} title={n.title} target="_blank" rel="noopener noreferrer">
            {renderInline(n.c, onOpenArtifact)}
          </a>
        );
      }
      default:
        return null;
    }
  });
}

function flattenText(nodes: Inline[]): string {
  return nodes
    .map((n) => {
      if (n.t === "text" || n.t === "code") return n.v;
      if (n.t === "img") return n.alt;
      if ("c" in n) return flattenText(n.c);
      return "";
    })
    .join("");
}

/**
 * Images render INLINE in the transcript rather than as a link to click.
 * A generated chart is the answer, not a footnote to it — making the reader
 * open a panel to see it breaks the reading flow the whole layout is built for.
 */
function InlineImage({
  src,
  alt,
  onOpen,
}: {
  src: string;
  alt: string;
  onOpen?: (a: Artifact) => void;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return <span className="text-xs italic text-fg-faint">{alt || "image unavailable"}</span>;
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      onClick={() =>
        onOpen?.({ name: alt || "Image", mime: guessMime(src), bytes: 0, url: src })
      }
      className={onOpen ? "cursor-zoom-in" : undefined}
    />
  );
}

function guessMime(url: string): string {
  const clean = (url.split("?")[0] || "").toLowerCase();
  if (/\.(png)$/.test(clean)) return "image/png";
  if (/\.(jpe?g)$/.test(clean)) return "image/jpeg";
  if (/\.(gif)$/.test(clean)) return "image/gif";
  if (/\.(webp)$/.test(clean)) return "image/webp";
  if (/\.svg$/.test(clean)) return "image/svg+xml";
  if (/\.pdf$/.test(clean)) return "application/pdf";
  if (/\.html?$/.test(clean)) return "text/html";
  if (/\.csv$/.test(clean)) return "text/csv";
  if (/\.json$/.test(clean)) return "application/json";
  if (/\.glb$/.test(clean)) return "model/gltf-binary";
  return "application/octet-stream";
}

/* ---------------------------------------------------------------- blocks */

const alignClass = (a: Align) =>
  a === "center" ? "text-center" : a === "right" ? "text-right" : "text-left";

function CodeBlock({ lang, code, open }: { lang: string; code: string; open: boolean }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked (insecure origin / old iOS) — the code is selectable */
    }
  }

  return (
    <div className="md-code group">
      <div className="md-code-bar">
        <span className="md-code-lang">{lang || "text"}</span>
        {/* While the fence is still open the content is mid-flight; offering a
            copy button then would hand the reader a truncated file. */}
        {!open && (
          <button type="button" onClick={copy} className="md-code-copy" aria-label="Copy code">
            {copied ? <IcoCheck size={12} /> : <IcoCopy size={12} />}
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>
        )}
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

function renderBlocks(blocks: Blk[], onOpen?: (a: Artifact) => void): React.ReactNode {
  return blocks.map((b, i) => {
    switch (b.t) {
      case "h": {
        const Tag = (`h${Math.min(6, Math.max(1, b.level))}`) as "h1";
        return <Tag key={i}>{renderInline(parseInline(b.text), onOpen)}</Tag>;
      }
      case "p":
        return <p key={i}>{renderInline(parseInline(b.text), onOpen)}</p>;
      case "hr":
        return <hr key={i} />;
      case "code":
        return <CodeBlock key={i} lang={b.lang} code={b.code} open={b.open} />;
      case "quote":
        return <blockquote key={i}>{renderBlocks(b.children, onOpen)}</blockquote>;
      case "list": {
        const items = b.items.map((it, j) => (
          <li key={j} className={it.checked === undefined ? undefined : "md-task"}>
            {it.checked !== undefined && (
              <input type="checkbox" checked={it.checked} readOnly tabIndex={-1} />
            )}
            <div className="md-li-body">{renderBlocks(it.children, onOpen)}</div>
          </li>
        ));
        return b.ordered ? (
          <ol key={i} start={b.start}>
            {items}
          </ol>
        ) : (
          <ul key={i}>{items}</ul>
        );
      }
      case "table":
        return (
          <div key={i} className="md-table-wrap">
            <table>
              <thead>
                <tr>
                  {b.head.map((h, j) => (
                    <th key={j} className={alignClass(b.align[j])}>
                      {renderInline(parseInline(h), onOpen)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c} className={alignClass(b.align[c])}>
                        {renderInline(parseInline(cell), onOpen)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      default:
        return null;
    }
  });
}

/* --------------------------------------------------------------- segment */

const Segment = memo(
  function Segment({
    content,
    onOpenArtifact,
  }: {
    content: string;
    onOpenArtifact?: (a: Artifact) => void;
  }) {
    const blocks = useMemo(() => parseBlocks(content), [content]);
    return <>{renderBlocks(blocks, onOpenArtifact)}</>;
  },
  (a, b) => a.content === b.content && a.onOpenArtifact === b.onOpenArtifact,
);

function MarkdownInner({
  text,
  streaming,
  onOpenArtifact,
}: {
  text: string;
  streaming?: boolean;
  onOpenArtifact?: (a: Artifact) => void;
}) {
  const segments = useMemo(() => splitSegments(text), [text]);
  const last = segments.length - 1;

  return (
    <div className="md">
      {segments.map((s, i) => (
        <div
          key={i}
          /* Settled segments are inert: containing them keeps the growing tail
             from invalidating layout for the whole answer on every frame. */
          className={streaming && i < last ? "block-settled" : undefined}
        >
          <Segment content={s} onOpenArtifact={onOpenArtifact} />
        </div>
      ))}
    </div>
  );
}

const Markdown = memo(MarkdownInner);
export default Markdown;
