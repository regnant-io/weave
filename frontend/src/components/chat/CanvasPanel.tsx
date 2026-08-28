"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Language } from "@/lib/types";
import { openSocket } from "@/lib/realtime";

/**
 * The shared canvas: one document, edited by the user and the assistant at the
 * same time.
 *
 * HOW THE TWO EDITORS COEXIST
 * ---------------------------
 * The server is authoritative and every accepted write bumps a revision. This
 * component sends whole-document writes carrying the revision it last saw; the
 * assistant sends anchored find/replace edits that rebase onto whatever the
 * document currently says. That asymmetry (see models.Canvas) is what lets both
 * work at once without character-wise transforms.
 *
 * Three behaviours make it feel collaborative rather than merely synchronised:
 *
 *  - **Remote writes land live** over the socket, but are NOT applied on top of
 *    unsaved local typing. Overwriting someone mid-sentence is the single worst
 *    thing a shared editor can do, so a remote change that arrives while the
 *    user is editing is held and offered.
 *  - **Local edits autosave** on a short debounce, so "save" is not a thing the
 *    user has to think about.
 *  - **A conflict is shown, never resolved silently.** If the revision moved
 *    under us the server rejects the write, and the user is given the choice.
 */

type Canvas = {
  id: string;
  title: string;
  content: string;
  revision: number;
  updated_by: string;
};

const AUTOSAVE_MS = 900;

export default function CanvasPanel({
  projectId,
  language,
}: {
  projectId: string;
  language: Language;
}) {
  const sw = language === "sw";
  const [canvas, setCanvas] = useState<Canvas | null>(null);
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "conflict" | "error">("idle");
  const [remote, setRemote] = useState<Canvas | null>(null);
  const [live, setLive] = useState(false);

  /** True while the user has typing the server has not accepted yet. */
  const dirty = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Mirrors `canvas` for use inside socket callbacks without re-subscribing. */
  const canvasRef = useRef<Canvas | null>(null);

  useEffect(() => {
    canvasRef.current = canvas;
  }, [canvas]);

  /* ---------------------------------------------------------------- load */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list: Canvas[] = await fetch(`/api/canvas/${projectId}`, { cache: "no-store" })
          .then((r) => r.json());
        if (cancelled || !Array.isArray(list) || !list.length) return;
        setCanvas(list[0]);
        setText(list[0].content ?? "");
      } catch {
        /* the panel is additive; a failed load must not break the chat */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  /* -------------------------------------------------------------- socket */
  useEffect(() => {
    if (!canvas?.id) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;

    async function connect() {
      const socket = await openSocket(`/ws/canvas/${canvas!.id}`);
      if (!socket || closed) {
        socket?.close();
        return;
      }
      ws = socket;
      ws.onopen = () => setLive(true);
      ws.onclose = () => {
        setLive(false);
        // A dropped socket mid-document is worth retrying; without this the
        // panel silently stops updating and looks like the assistant stopped.
        if (!closed) retry = setTimeout(connect, 3000);
      };
      ws.onmessage = (event) => {
        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }
        if (payload.type === "ping") return;
        if (payload.type !== "snapshot" && payload.type !== "update") return;

        const incoming: Canvas = {
          id: String(payload.canvas_id ?? canvasRef.current?.id ?? ""),
          title: String(payload.title ?? canvasRef.current?.title ?? ""),
          content: String(payload.content ?? ""),
          revision: Number(payload.revision ?? 0),
          updated_by: String(payload.updated_by ?? "assistant"),
        };
        if (incoming.revision <= (canvasRef.current?.revision ?? -1)) return;

        if (dirty.current) {
          // Never clobber unsaved typing — offer it instead.
          setRemote(incoming);
          return;
        }
        setCanvas(incoming);
        setText(incoming.content);
        setStatus("idle");
      };
    }

    void connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, [canvas?.id]);

  /* ---------------------------------------------------------------- save */
  const save = useCallback(
    async (value: string) => {
      const current = canvasRef.current;
      if (!current) return;
      setStatus("saving");
      try {
        const res = await fetch(`/api/canvas/${projectId}/${current.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: value, base_revision: current.revision }),
        });
        if (res.status === 409) {
          const body = await res.json().catch(() => ({}));
          const theirs = body?.detail?.current ?? body?.current;
          if (theirs) setRemote(theirs as Canvas);
          setStatus("conflict");
          return;
        }
        if (!res.ok) {
          setStatus("error");
          return;
        }
        const saved: Canvas = await res.json();
        setCanvas(saved);
        dirty.current = false;
        setStatus("saved");
      } catch {
        setStatus("error");
      }
    },
    [projectId],
  );

  function onChange(value: string) {
    setText(value);
    dirty.current = true;
    setStatus("idle");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void save(value), AUTOSAVE_MS);
  }

  function takeRemote() {
    if (!remote) return;
    setCanvas(remote);
    setText(remote.content);
    setRemote(null);
    dirty.current = false;
    setStatus("idle");
  }

  function keepMine() {
    if (!remote) return;
    // Rebase onto their revision and push our text over it. The user has seen
    // both and chosen; forcing them through a manual merge here would be worse.
    setCanvas({ ...remote, content: text });
    setRemote(null);
    dirty.current = true;
    void save(text);
  }

  if (!canvas) {
    return (
      <p className="px-3 py-6 text-center text-xs text-fg-faint">
        {sw ? "Inapakia hati…" : "Loading the document…"}
      </p>
    );
  }

  const statusLabel =
    status === "saving"
      ? sw ? "Inahifadhi…" : "Saving…"
      : status === "saved"
        ? sw ? "Imehifadhiwa" : "Saved"
        : status === "error"
          ? sw ? "Haikuhifadhiwa" : "Not saved"
          : status === "conflict"
            ? sw ? "Mgongano" : "Conflict"
            : "";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-3 py-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{canvas.title}</span>
        <span className="font-mono text-[10px] text-fg-faint">r{canvas.revision}</span>
        <span
          title={live ? "live" : "reconnecting"}
          className={`h-1.5 w-1.5 rounded-full ${live ? "bg-accent" : "bg-fg-faint"}`}
        />
        {statusLabel && (
          <span
            className={`text-[11px] ${status === "error" || status === "conflict" ? "text-danger" : "text-fg-faint"}`}
          >
            {statusLabel}
          </span>
        )}
        {canvas.updated_by === "assistant" && !dirty.current && (
          <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[10px] text-accent">
            {sw ? "Weave amehariri" : "Weave edited"}
          </span>
        )}
      </div>

      {remote && (
        <div className="border-b border-border bg-surface-2 px-3 py-2">
          <p className="text-[11.5px] leading-relaxed text-fg-muted">
            {sw
              ? "Hati ilibadilika wakati unaandika. Chagua toleo la kutumia."
              : "The document changed while you were typing. Choose which version to keep."}
          </p>
          <div className="mt-1.5 flex gap-1.5">
            <button
              onClick={takeRemote}
              className="rounded-full border border-border px-2.5 py-1 text-[11.5px] hover:border-accent-line hover:text-accent"
            >
              {sw ? "Tumia yao" : "Take theirs"}
            </button>
            <button
              onClick={keepMine}
              className="rounded-full border border-border px-2.5 py-1 text-[11.5px] hover:border-accent-line hover:text-accent"
            >
              {sw ? "Weka yangu" : "Keep mine"}
            </button>
          </div>
        </div>
      )}

      <textarea
        value={text}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
        placeholder={
          sw
            ? "Andika hapa. Weave anaweza kuhariri hati hii pamoja nawe."
            : "Write here. Weave can edit this document alongside you."
        }
        className="min-h-0 flex-1 resize-none bg-bg px-3 py-3 font-mono text-[13px] leading-relaxed outline-none placeholder:text-fg-faint"
      />

      <div className="border-t border-border px-3 py-1.5">
        <p className="text-[10.5px] leading-relaxed text-fg-faint">
          {sw
            ? "Weave anaisoma kabla ya kuhariri, na hubadilisha sehemu husika tu."
            : "Weave reads this before editing, and changes only the passage it means to."}
        </p>
      </div>
    </div>
  );
}
