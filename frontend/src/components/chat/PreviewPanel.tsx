"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Language } from "@/lib/types";
import { IcoExternal, IcoRetry, IcoStop } from "@/components/ui/icons";

/**
 * The app the assistant is running, live.
 *
 * WHY THIS IS AN IFRAME TO LOCALHOST AND NOT A SCREENSHOT
 * ------------------------------------------------------
 * The assistant can now start a real dev server in the project's container and
 * the port is published to the host loopback, so the user's own browser can
 * reach it. That means the preview is the ACTUAL APPLICATION — clickable,
 * typeable, with its own state — rather than a picture of one. The difference
 * matters most for exactly the things a screenshot cannot show: whether the
 * button does anything, whether the form validates, whether it is usable on a
 * narrow screen.
 *
 * The frame is deliberately NOT sandboxed the way generated artifacts are.
 * An artifact is untrusted model output rendered under `sandbox="allow-scripts"`
 * in an opaque origin. This is a dev server the user asked the assistant to
 * start, on their own machine, and it needs storage and same-origin XHR to be
 * the app it is. Sandboxing it would show a broken version of a working thing.
 */

const LABELS = {
  en: {
    title: "Live app",
    idle: "No app is running. Ask for something to be built and served, and it appears here.",
    reload: "Reload",
    open: "Open in a new tab",
    stopped: "The server was stopped.",
    device: { desktop: "Desktop", tablet: "Tablet", phone: "Phone" },
  },
  sw: {
    title: "Programu hai",
    idle: "Hakuna programu inayoendeshwa. Omba kitu kijengwe na kiendeshwe, kitaonekana hapa.",
    reload: "Pakia upya",
    open: "Fungua kwenye kichupo kipya",
    stopped: "Seva imesimamishwa.",
    device: { desktop: "Kompyuta", tablet: "Tableti", phone: "Simu" },
  },
} as const;

type Device = "desktop" | "tablet" | "phone";

/** Real device widths — a "responsive check" against invented numbers is theatre. */
const WIDTHS: Record<Device, number | null> = {
  desktop: null,
  tablet: 820,
  phone: 390,
};

export default function PreviewPanel({
  url,
  language,
}: {
  url: string;
  language: Language;
}) {
  const t = LABELS[language] ?? LABELS.en;
  const [device, setDevice] = useState<Device>("desktop");
  // Bumped to force a remount. Changing an iframe's `src` to the same value
  // does not reload it, and `contentWindow.location.reload()` is cross-origin
  // here — remounting is the only reload that actually works.
  const [nonce, setNonce] = useState(0);
  const lastUrl = useRef(url);

  useEffect(() => {
    // A new server on a new port is a new app; show it from the start.
    if (url && url !== lastUrl.current) {
      lastUrl.current = url;
      setNonce((n) => n + 1);
    }
  }, [url]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  if (!url) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <p className="max-w-[34ch] text-center text-sm leading-relaxed text-fg-muted">
          {t.idle}
        </p>
      </div>
    );
  }

  const width = WIDTHS[device];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-1 border-b border-border px-2 py-1.5">
        {(Object.keys(WIDTHS) as Device[]).map((d) => (
          <button
            key={d}
            onClick={() => setDevice(d)}
            className={`px-2 py-1 text-2xs uppercase tracking-widest transition-colors duration-fast ${
              device === d
                ? "bg-fg text-bg"
                : "text-fg-faint hover:text-fg"
            }`}
          >
            {t.device[d]}
          </button>
        ))}

        <span className="ml-2 truncate font-mono text-2xs text-fg-faint">{url}</span>

        <button
          onClick={reload}
          title={t.reload}
          aria-label={t.reload}
          className="ml-auto grid h-7 w-7 place-items-center text-fg-faint transition-colors duration-fast hover:text-fg"
        >
          <IcoRetry size={13} />
        </button>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          title={t.open}
          aria-label={t.open}
          className="grid h-7 w-7 place-items-center text-fg-faint transition-colors duration-fast hover:text-fg"
        >
          <IcoExternal size={13} />
        </a>
      </div>

      <div className="flex min-h-0 flex-1 justify-center overflow-auto bg-surface-2 p-2">
        <iframe
          key={`${url}#${nonce}`}
          src={url}
          title={t.title}
          className="h-full border border-border bg-white"
          style={{ width: width ? `${width}px` : "100%", maxWidth: "100%" }}
        />
      </div>
    </div>
  );
}
