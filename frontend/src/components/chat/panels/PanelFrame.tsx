"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { IcoClose } from "@/components/ui/icons";

const MIN_W = 300;
const MAX_FRACTION = 0.55;

/**
 * Chrome shared by every right-hand panel.
 *
 * Each panel is an INDEPENDENT surface, not a tab inside a shared shell: it
 * owns its own width (persisted per panel id, so the charts panel can be wide
 * and the sources panel narrow), its own scroll position, its own resize grip,
 * and its own close button. The dock only decides which panels are open and in
 * what order.
 */
export default function PanelFrame({
  id,
  title,
  count,
  icon: Icon,
  onClose,
  children,
  defaultWidth = 420,
}: {
  id: string;
  title: string;
  count?: number;
  icon: any;
  onClose: () => void;
  children: React.ReactNode;
  defaultWidth?: number;
}) {
  const [width, setWidth] = useState(defaultWidth);
  const [dragging, setDragging] = useState(false);
  const startX = useRef(0);
  const startW = useRef(0);

  const storeKey = `weave.panel.${id}.width`;

  useEffect(() => {
    const saved = Number(localStorage.getItem(storeKey));
    if (saved >= MIN_W) setWidth(saved);
  }, [storeKey]);

  const maxW = () => Math.max(MIN_W, Math.round(window.innerWidth * MAX_FRACTION));

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    startX.current = e.clientX;
    startW.current = width;
    setDragging(true);
  }, [width]);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging) return;
      // Dragging LEFT widens the panel, so the delta is inverted.
      const next = startW.current + (startX.current - e.clientX);
      setWidth(Math.min(maxW(), Math.max(MIN_W, next)));
    },
    [dragging],
  );

  const endDrag = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging) return;
      try {
        (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
      } catch {
        /* already released */
      }
      setDragging(false);
      localStorage.setItem(storeKey, String(width));
    },
    [dragging, width, storeKey],
  );

  return (
    <section
      aria-label={title}
      /*
        `width` is the DESIRED width and `flexBasis` lets the row squeeze it when
        the conversation would otherwise be crushed — two panels at their
        preferred widths can leave the transcript with under 100px, which is
        worse than a narrower panel. minWidth keeps a squeezed panel legible.
      */
      style={{ width, flexBasis: width, minWidth: 264 }}
      className={`panel-enter relative flex h-full min-h-0 shrink flex-col border-l border-border bg-bg-subtle
        max-lg:!w-full max-lg:!basis-auto ${dragging ? "" : "transition-[flex-basis] duration-panel ease-expo"}`}
    >
      {/* Resize grip, centred on this panel's own left border. */}
      <div
        className="resize-handle max-lg:hidden"
        data-dragging={dragging}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize ${title}`}
      >
        <span className="pointer-events-none h-10 w-[3px] rounded-full bg-border-mid" />
      </div>

      <header className="flex flex-shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <Icon size={15} className="flex-shrink-0 text-accent" />
        <h2 className="min-w-0 flex-1 truncate text-[13px] font-medium">{title}</h2>
        {count !== undefined && count > 0 && (
          <span className="font-mono text-[10.5px] text-fg-faint">{count}</span>
        )}
        <button
          onClick={onClose}
          aria-label={`Close ${title}`}
          className="grid h-6 w-6 flex-shrink-0 place-items-center text-fg-faint transition-colors duration-fast hover:text-fg"
        >
          <IcoClose size={14} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">{children}</div>
    </section>
  );
}

export function PanelEmpty({ text }: { text: string }) {
  return (
    <div className="tx-lines relative flex h-40 items-center justify-center border border-dashed border-border">
      <p className="relative z-[1] px-6 text-center text-xs text-fg-faint">{text}</p>
    </div>
  );
}
