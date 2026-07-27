"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type { ThemePref } from "@/lib/session";
import type { Language } from "@/lib/types";

type Health = {
  llm_engine: string;
  embedding_backend: string;
  sandbox_backend: string;
  database: string;
  tools: string[];
  capabilities: Record<string, boolean>;
} | null;

const applyTheme = (pref: ThemePref) => {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
};

export default function SettingsClient({
  language,
  theme,
  lite,
  account,
  health,
}: {
  language: Language;
  theme: ThemePref;
  lite: boolean;
  account: { phone: string | null; email: string | null; role: string; trust_tier: string; phone_verified: boolean };
  health: Health;
}) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [themePref, setThemePref] = useState<ThemePref>(theme);
  const [lang, setLang] = useState<Language>(language);
  const [liteMode, setLiteMode] = useState(lite);
  const sw = lang === "sw";

  async function save(patch: Record<string, unknown>) {
    await fetch("/api/prefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    startTransition(() => router.refresh());
  }

  return (
    <div className="space-y-6">
      {/* Appearance */}
      <Section title={sw ? "Muonekano" : "Appearance"}>
        <Row label={sw ? "Mandhari" : "Theme"}>
          <Segmented
            value={themePref}
            options={[
              ["light", sw ? "Mwanga" : "Light"],
              ["dark", sw ? "Giza" : "Dark"],
              ["system", sw ? "Mfumo" : "System"],
            ]}
            onChange={(v) => { setThemePref(v as ThemePref); applyTheme(v as ThemePref); save({ theme: v }); }}
          />
        </Row>
        <Row label={sw ? "Lugha" : "Language"}>
          <Segmented
            value={lang}
            options={[["sw", "Kiswahili"], ["en", "English"]]}
            onChange={(v) => { setLang(v as Language); save({ language: v }); }}
          />
        </Row>
        <Row label={sw ? "Hali ya data ndogo" : "Lite mode"} hint={sw ? "Chati kama picha, data kidogo" : "Charts as images, less data"}>
          <Toggle checked={liteMode} onChange={(v) => { setLiteMode(v); save({ lite: v }); }} />
        </Row>
      </Section>

      {/* Account */}
      <Section title={sw ? "Akaunti" : "Account"}>
        <Info label={sw ? "Simu" : "Phone"} value={account.phone ?? "—"} />
        <Info label="Email" value={account.email ?? "—"} />
        <Info label={sw ? "Jukumu" : "Role"} value={account.role} />
        <Info label={sw ? "Kiwango" : "Trust tier"} value={account.trust_tier} />
        <Info label={sw ? "Simu imethibitishwa" : "Phone verified"} value={account.phone_verified ? "✓" : "✗"} />
      </Section>

      {/* System / capabilities */}
      {health && health.llm_engine && (
        <Section title={sw ? "Mfumo na uwezo" : "System & capabilities"}>
          <Info label="LLM engine" value={health.llm_engine} />
          <Info label={sw ? "Embeddings" : "Embeddings"} value={health.embedding_backend} />
          <Info label="Sandbox" value={health.sandbox_backend} />
          <Info label="Database" value={health.database} />
          {health.tools && health.tools.length > 0 && (
            <div className="pt-2">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-faint">
                {sw ? "Zana zinazopatikana" : "Available tools"}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {health.tools.map((tool) => (
                  <span key={tool} className="rounded-sm bg-surface-2 px-2 py-1 text-xs text-fg-muted">{tool}</span>
                ))}
              </div>
            </div>
          )}
          {health.capabilities && Object.keys(health.capabilities).length > 0 && (
            <div className="pt-3">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-faint">
                {sw ? "Huduma" : "Services"}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(health.capabilities).map(([k, on]) => (
                  <span
                    key={k}
                    className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs ${
                      on ? "bg-accent-soft text-accent" : "bg-surface-2 text-fg-faint"
                    }`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${on ? "bg-accent" : "bg-fg-faint"}`} />
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className=" border border-border bg-surface p-5">
      <h2 className="mb-4 text-sm font-semibold">{title}</h2>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="text-sm">{label}</div>
        {hint && <div className="text-xs text-fg-faint">{hint}</div>}
      </div>
      {children}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-fg-muted">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function Segmented({ value, options, onChange }: { value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex rounded-full border border-border bg-surface-2 p-0.5 text-sm">
      {options.map(([val, label]) => (
        <button
          key={val}
          onClick={() => onChange(val)}
          className={`rounded-full px-3 py-1 transition-colors ${
            value === val ? "bg-accent text-accent-fg" : "text-fg-muted hover:text-fg"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      aria-pressed={checked}
      className={`relative h-6 w-11 rounded-full transition-colors ${checked ? "bg-accent" : "bg-surface-2 border border-border"}`}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "left-0.5 translate-x-5" : "left-0.5"}`}
      />
    </button>
  );
}
