"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Artifact, Language } from "@/lib/types";
import { Panel, categorise, type PanelData, type PanelId } from "./panels";

/**
 * Hosts the open right-hand panels.
 *
 * Panels are independent surfaces, and more than one can be open at a time —
 * comparing a chart against the sources that produced it is a normal thing to
 * want, and forcing that through a tab switch loses the comparison. The dock
 * only owns which panels are open and their order; each panel owns its own
 * width, scroll and focused artifact.
 *
 * Desktop caps the stack so the conversation always keeps usable width; opening
 * one more closes the least recently opened. Mobile shows one at a time as a
 * sheet, because side-by-side is meaningless at 360px.
 */
/**
 * How many panels may be open at once, given the viewport.
 *
 * Two independent panels side by side is genuinely useful — a chart next to the
 * sources behind it — but only when the conversation still has room to read. At
 * 1280px, two preferred-width panels leave the transcript under 100px wide, so
 * the second panel is gated on having the space for it.
 */
function maxOpen(): number {
  if (typeof window === "undefined") return 1;
  if (window.matchMedia("(max-width: 1023px)").matches) return 1;
  return window.innerWidth >= 1500 ? 2 : 1;
}

export function usePanelDock() {
  const [open, setOpen] = useState<PanelId[]>([]);
  const [isNarrow, setIsNarrow] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1023px)");
    const sync = () => {
      setIsNarrow(mq.matches);
      setOpen((prev) => (prev.length > maxOpen() ? prev.slice(prev.length - maxOpen()) : prev));
    };
    sync();
    mq.addEventListener("change", sync);
    window.addEventListener("resize", sync);
    return () => {
      mq.removeEventListener("change", sync);
      window.removeEventListener("resize", sync);
    };
  }, []);

  const openPanel = useCallback(
    (id: PanelId) => {
      setOpen((prev) => {
        if (prev.includes(id)) return prev;
        const limit = maxOpen();
        const next = [...prev, id];
        return next.length > limit ? next.slice(next.length - limit) : next;
      });
    },
    [],
  );

  const closePanel = useCallback((id: PanelId) => {
    setOpen((prev) => prev.filter((p) => p !== id));
  }, []);

  const closeAll = useCallback(() => setOpen([]), []);

  const toggle = useCallback((id: PanelId) => {
    setOpen((prev) => {
      if (prev.includes(id)) return prev.filter((p) => p !== id);
      const limit = maxOpen();
      const next = [...prev, id];
      return next.length > limit ? next.slice(next.length - limit) : next;
    });
  }, []);

  /*
    Memoised, because this object is a dependency.

    Returning a fresh literal every render meant any `useCallback` that closed
    over the dock — `openArtifact` in ChatClient, for one — got a new identity
    on every render too. That callback is a prop on every turn in the
    transcript, so it silently defeated memoisation for the entire conversation
    and made each streamed token re-render every turn ever sent.
  */
  return useMemo(
    () => ({ open, openPanel, closePanel, closeAll, toggle, isNarrow }),
    [open, openPanel, closePanel, closeAll, toggle, isNarrow],
  );
}

export default function PanelDock({
  open,
  data,
  language,
  onClose,
  onCloseAll,
}: {
  open: PanelId[];
  data: PanelData;
  language: Language;
  onClose: (id: PanelId) => void;
  onCloseAll: () => void;
}) {
  // Escape closes the most recently opened panel, not all of them — matching
  // how a stack of surfaces is normally dismissed.
  useEffect(() => {
    if (!open.length) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose(open[open.length - 1]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      {/* Mobile scrim: panels are a sheet over the conversation at this size. */}
      <div
        onClick={onCloseAll}
        className={`fixed inset-0 z-[45] bg-black/40 transition-opacity duration-panel ease-expo lg:hidden ${
          open.length ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      <div
        className={`z-[46] flex min-h-0 min-w-0 max-lg:fixed max-lg:inset-y-0 max-lg:right-0 max-lg:w-[min(92vw,460px)]
          max-lg:transition-transform max-lg:duration-panel max-lg:ease-expo ${
            open.length ? "max-lg:translate-x-0" : "max-lg:translate-x-full"
          }`}
      >
        {open.map((id) => (
          <Panel key={id} id={id} data={data} language={language} onClose={() => onClose(id)} />
        ))}
      </div>
    </>
  );
}

/** Which panel should receive a given artifact when it is clicked in chat. */
export function panelForArtifact(a: Artifact): PanelId {
  return categorise(a);
}
