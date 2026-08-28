"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import type { Language } from "@/lib/types";

export default function DatasetUpload({ projectId, language }: { projectId: string; language: Language }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function upload(file: File) {
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/datasets/${projectId}`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: form,
    });
    setBusy(false);
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setError(d.detail ?? d.error ?? "upload failed");
      return;
    }
    router.refresh();
  }

  return (
    <div className="inline-flex flex-col items-end">
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.tsv,.xlsx,.xls,.json"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); }}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="rounded-sm border border-border px-2.5 py-1.5 text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-60"
      >
        {busy ? (language === "sw" ? "Inapakia…" : "Uploading…") : (language === "sw" ? "+ Data" : "+ Data")}
      </button>
      {error && <span className="mt-1 text-xs text-danger">{error}</span>}
    </div>
  );
}
