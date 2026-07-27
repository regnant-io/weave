"use client";

import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Artifact } from "@/lib/types";

/**
 * Streaming-stable markdown.
 *
 * Re-parsing the whole answer on every token gets quadratically slower as the
 * answer grows — the "slows down after a long run" problem. We split on blank
 * lines (never inside a fence) and memoise each finalised block, so completed
 * prose parses exactly once and never re-renders. Only the last, still-growing
 * block re-parses per frame, and it is small, so per-token cost stays flat no
 * matter how long the document gets.
 */
function splitIntoBlocks(text: string): string[] {
  const lines = text.split("\n");
  const blocks: string[] = [];
  let cur: string[] = [];
  let inFence = false;
  for (const line of lines) {
    if (/^\s*```/.test(line)) inFence = !inFence;
    if (line.trim() === "" && !inFence) {
      if (cur.length) {
        blocks.push(cur.join("\n"));
        cur = [];
      }
    } else {
      cur.push(line);
    }
  }
  if (cur.length) blocks.push(cur.join("\n"));
  return blocks;
}

/**
 * In-chat links route to the right panel rather than a new tab, so generated
 * and cited content is viewed beside the conversation instead of replacing it.
 * External links the panel can't host still open normally.
 */
function makeComponents(onOpen?: (a: Artifact) => void) {
  return {
    a: ({ href, children, ...rest }: any) => {
      const url = String(href ?? "");
      const isArtifact = url.startsWith("/api/artifact/");
      if (isArtifact && onOpen) {
        return (
          <button
            type="button"
            onClick={() =>
              onOpen({
                name: String(children ?? "Artifact"),
                mime: guessMime(url),
                bytes: 0,
                url,
              })
            }
            className="text-accent underline decoration-accent-line underline-offset-2 transition-colors duration-fast hover:decoration-accent"
          >
            {children}
          </button>
        );
      }
      return (
        <a href={url} target="_blank" rel="noopener noreferrer" {...rest}>
          {children}
        </a>
      );
    },
    img: ({ src, alt }: any) => (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={String(src ?? "")}
        alt={String(alt ?? "")}
        loading="lazy"
        decoding="async"
        onClick={() =>
          onOpen?.({ name: String(alt || "Image"), mime: "image/*", bytes: 0, url: String(src ?? "") })
        }
        className="cursor-zoom-in"
      />
    ),
  };
}

function guessMime(url: string): string {
  const clean = url.split("?")[0].toLowerCase();
  if (clean.endsWith(".png") || clean.endsWith(".jpg") || clean.endsWith(".jpeg")) return "image/png";
  if (clean.endsWith(".svg")) return "image/svg+xml";
  if (clean.endsWith(".pdf")) return "application/pdf";
  if (clean.endsWith(".html")) return "text/html";
  if (clean.endsWith(".csv")) return "text/csv";
  if (clean.endsWith(".glb")) return "model/gltf-binary";
  return "application/octet-stream";
}

const Block = memo(function Block({
  content,
  components,
}: {
  content: string;
  components: any;
}) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  );
});

function MarkdownInner({
  text,
  streaming,
  onOpenArtifact,
}: {
  text: string;
  streaming?: boolean;
  onOpenArtifact?: (a: Artifact) => void;
}) {
  const blocks = useMemo(() => splitIntoBlocks(text), [text]);
  const components = useMemo(() => makeComponents(onOpenArtifact), [onOpenArtifact]);
  const last = blocks.length - 1;

  return (
    <div className="md">
      {blocks.map((b, i) => (
        <div key={i} className={streaming && i < last ? "block-settled" : undefined}>
          <Block content={b} components={components} />
        </div>
      ))}
    </div>
  );
}

const Markdown = memo(MarkdownInner);
export default Markdown;
