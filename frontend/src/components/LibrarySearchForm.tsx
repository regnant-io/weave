"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Language } from "@/lib/types";
import { t } from "@/lib/i18n";

export default function LibrarySearchForm({ language, initial }: { language: Language; initial: string }) {
  const router = useRouter();
  const [q, setQ] = useState(initial);
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); router.push(`/app/library?q=${encodeURIComponent(q)}`); }}
      className="mb-6 flex gap-2"
    >
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t("searchLibrary", language)}
        className="flex-1 rounded-full border border-border bg-surface px-4 py-2.5 outline-none transition-colors focus:border-border-strong placeholder:text-fg-faint"
      />
      <button className="rounded-full bg-accent px-5 py-2.5 font-medium text-accent-fg transition-opacity hover:opacity-90">
        {language === "sw" ? "Tafuta" : "Search"}
      </button>
    </form>
  );
}
