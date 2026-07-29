"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type { ThemePref } from "@/lib/session";
import type { Effort, Language } from "@/lib/types";
import { ALL_SERVICES, type ServiceId, type ServicePrefs } from "@/lib/services";
import { formatTokens } from "@/lib/models";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { IcoTrash } from "@/components/ui/icons";

type Health = {
  llm_engine: string;
  embedding_backend: string;
  sandbox_backend: string;
  database: string;
  tools: string[];
  capabilities: Record<string, boolean>;
} | null;

type WorkspaceStatus = {
  enabled: boolean;
  image: string;
  network: boolean;
  memory_mb: number;
  cpus: number;
  default_timeout: number;
} | null;

const applyTheme = (pref: ThemePref) => {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
};

/**
 * Coerce anything the API hands us into a renderable string.
 *
 * React throws error #31 ("objects are not valid as a React child") for an
 * object, and in a production build the message is minified to an unreadable
 * code — which is how a shape change in one endpoint took this whole page down.
 * Every value that crosses the network boundary goes through here.
 */
function asText(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v || "—";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(asText).join(", ");
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.name === "string") return o.name;
    if (typeof o.label === "string") return o.label;
    try {
      return JSON.stringify(v);
    } catch {
      return "—";
    }
  }
  return String(v);
}

const SERVICE_LABELS: Record<ServiceId, [string, string]> = {
  web_search: ["Utafutaji wa mtandao", "Web search"],
  deep_research: ["Utafiti wa kina", "Deep research"],
  analysis: ["Uchambuzi wa data", "Data analysis"],
  visuals: ["Taswira na 3D", "Visuals & 3D"],
};

const EFFORTS: { id: Effort; label: string; hint: [string, string] }[] = [
  { id: "spool", label: "Spool", hint: ["Majibu mafupi, haraka", "Short answers, fast"] },
  { id: "weave", label: "Weave", hint: ["Sawia — chaguo-msingi", "Balanced — the default"] },
  {
    id: "tapestry",
    label: "Tapestry",
    hint: ["Kina, hutumia zana kwa wingi", "Deep; uses tools liberally"],
  },
];

export default function SettingsClient({
  language,
  theme,
  lite,
  effort,
  services,
  account,
  health,
  workspace,
  contextWindow,
  currentModel,
}: {
  language: Language;
  theme: ThemePref;
  lite: boolean;
  effort: Effort;
  services: ServicePrefs;
  account: {
    phone: string | null;
    email: string | null;
    role: string;
    trust_tier: string;
    phone_verified: boolean;
  };
  health: Health;
  workspace: WorkspaceStatus;
  contextWindow: number;
  currentModel: string;
}) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [themePref, setThemePref] = useState<ThemePref>(theme);
  const [lang, setLang] = useState<Language>(language);
  const [liteMode, setLiteMode] = useState(lite);
  const [effortPref, setEffortPref] = useState<Effort>(effort);
  const [servicePrefs, setServicePrefs] = useState<ServicePrefs>(services);
  const [confirmWipe, setConfirmWipe] = useState(false);
  const [wipeResult, setWipeResult] = useState<string | null>(null);
  const sw = lang === "sw";

  async function save(patch: Record<string, unknown>) {
    await fetch("/api/prefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).catch(() => {});
    startTransition(() => router.refresh());
  }

  function toggleService(id: ServiceId) {
    const next = { ...servicePrefs, [id]: !servicePrefs[id] };
    setServicePrefs(next);
    void save({ services: next });
  }

  async function deleteEverything() {
    setConfirmWipe(false);
    try {
      const res = await fetch("/api/projects?confirm=DELETE", { method: "DELETE" });
      if (!res.ok) throw new Error();
      const body = await res.json().catch(() => ({}));
      setWipeResult(
        sw
          ? `Miradi ${body.deleted ?? 0} imefutwa.`
          : `Deleted ${body.deleted ?? 0} project(s).`,
      );
      startTransition(() => router.refresh());
    } catch {
      setWipeResult(sw ? "Imeshindwa kufuta." : "Could not delete your projects.");
    }
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
            onChange={(v) => {
              setThemePref(v as ThemePref);
              applyTheme(v as ThemePref);
              void save({ theme: v });
            }}
          />
        </Row>
        <Row label={sw ? "Lugha" : "Language"}>
          <Segmented
            value={lang}
            options={[
              ["sw", "Kiswahili"],
              ["en", "English"],
            ]}
            onChange={(v) => {
              setLang(v as Language);
              void save({ language: v });
            }}
          />
        </Row>
        <Row
          label={sw ? "Hali ya data ndogo" : "Lite mode"}
          hint={sw ? "Chati kama picha, data kidogo" : "Charts as images, less data"}
        >
          <Toggle
            checked={liteMode}
            onChange={(v) => {
              setLiteMode(v);
              void save({ lite: v });
            }}
          />
        </Row>
      </Section>

      {/* Chat behaviour */}
      <Section
        title={sw ? "Tabia ya mazungumzo" : "Chat behaviour"}
        note={
          sw
            ? "Chaguo hizi ni chaguo-msingi za gumzo jipya; unaweza kubadilisha kwa kila gumzo kwenye upau wa kuandika."
            : "These are defaults for new chats — you can override them per chat from the composer."
        }
      >
        <Row label={sw ? "Kina cha kazi" : "Effort"} hint={sw ? "Loom" : "Loom level"}>
          <Segmented
            value={effortPref}
            options={EFFORTS.map((e) => [e.id, e.label] as [string, string])}
            onChange={(v) => {
              setEffortPref(v as Effort);
              void save({ effort: v });
            }}
          />
        </Row>
        <p className="-mt-2 text-xs text-fg-faint">
          {sw
            ? EFFORTS.find((e) => e.id === effortPref)?.hint[0]
            : EFFORTS.find((e) => e.id === effortPref)?.hint[1]}
        </p>

        <div className="pt-1">
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-faint">
            {sw ? "Huduma zinazotumika kila wakati" : "Always-on services"}
          </div>
          <div className="space-y-2.5">
            {ALL_SERVICES.map((id) => (
              <Row key={id} label={SERVICE_LABELS[id][sw ? 0 : 1]}>
                <Toggle checked={Boolean(servicePrefs[id])} onChange={() => toggleService(id)} />
              </Row>
            ))}
          </div>
        </div>
      </Section>

      {/* Model + context */}
      <Section
        title={sw ? "Modeli na muktadha" : "Model & context"}
        note={
          sw
            ? "Dirisha la muktadha husomwa kutoka kwa modeli yenyewe. Gumzo linapofika kikomo, hufupishwa kiotomatiki na kuendelea kwenye gumzo jipya bila kupoteza kile kilichokwisha kubalika."
            : "The context window is read from the model itself. When a chat reaches it, it is summarised automatically and continued in a new chat, so nothing already established is lost."
        }
      >
        <Info label={sw ? "Modeli" : "Model"} value={currentModel || "—"} />
        <Info
          label={sw ? "Dirisha la muktadha" : "Context window"}
          value={contextWindow ? `${formatTokens(contextWindow)} tokens` : "—"}
        />
        <Info label={sw ? "Injini" : "Engine"} value={health?.llm_engine} />
      </Section>

      {/* Developer workspace */}
      <Section
        title={sw ? "Eneo la kazi la msanidi" : "Developer workspace"}
        note={
          sw
            ? "Eneo la kudumu kwa kila mradi ambapo AI hujenga programu: husakinisha vifurushi, huendesha majaribio na hufunga matokeo. Ni tofauti na sanduku la uchambuzi wa data, ambalo halina mtandao kwa makusudi."
            : "A persistent per-project directory where the assistant builds software — installing packages, running tests, packaging results. Separate from the data-analysis sandbox, which stays offline by design."
        }
      >
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="text-fg-muted">{sw ? "Hali" : "Status"}</span>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] ${
              workspace?.enabled ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${workspace?.enabled ? "bg-ok" : "bg-warn"}`}
            />
            {workspace?.enabled
              ? sw
                ? "Inapatikana"
                : "Available"
              : sw
                ? "Docker haipatikani"
                : "Docker unavailable"}
          </span>
        </div>
        {workspace && (
          <>
            <Info label="Image" value={workspace.image} />
            <Info
              label={sw ? "Rasilimali" : "Resources"}
              value={`${workspace.memory_mb} MB · ${workspace.cpus} CPU`}
            />
            <Info
              label={sw ? "Mtandao" : "Network"}
              value={
                workspace.network
                  ? sw
                    ? "Umewashwa (kwa kusakinisha vifurushi)"
                    : "Enabled (for installing dependencies)"
                  : sw
                    ? "Umezimwa"
                    : "Disabled"
              }
            />
          </>
        )}
        {!workspace?.enabled && (
          <p className="text-xs leading-relaxed text-fg-faint">
            {sw
              ? "Jenga picha kisha washa Docker: docker build -t weave-workspace:latest ./workspace-image"
              : "Build the image and start Docker: docker build -t weave-workspace:latest ./workspace-image"}
          </p>
        )}
      </Section>

      {/* Account */}
      <Section title={sw ? "Akaunti" : "Account"}>
        <Info label={sw ? "Simu" : "Phone"} value={account.phone} />
        <Info label="Email" value={account.email} />
        <Info label={sw ? "Jukumu" : "Role"} value={account.role} />
        <Info label={sw ? "Kiwango" : "Trust tier"} value={account.trust_tier} />
        <Info
          label={sw ? "Simu imethibitishwa" : "Phone verified"}
          value={account.phone_verified ? "✓" : "✗"}
        />
      </Section>

      {/* System / capabilities */}
      {health && health.llm_engine && (
        <Section title={sw ? "Mfumo na uwezo" : "System & capabilities"}>
          <Info label={sw ? "Embeddings" : "Embeddings"} value={health.embedding_backend} />
          <Info label="Sandbox" value={health.sandbox_backend} />
          <Info label="Database" value={health.database} />
          {health.tools && health.tools.length > 0 && (
            <div className="pt-2">
              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-faint">
                {sw ? "Zana zinazopatikana" : "Available tools"} ({health.tools.length})
              </div>
              <div className="flex flex-wrap gap-1.5">
                {health.tools.map((tool, i) => (
                  <span
                    key={`${asText(tool)}-${i}`}
                    className="rounded-sm bg-surface-2 px-2 py-1 text-xs text-fg-muted"
                  >
                    {asText(tool)}
                  </span>
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
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${on ? "bg-accent" : "bg-fg-faint"}`}
                    />
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}
        </Section>
      )}

      {/* Data management — last, and visually separated. */}
      <section className="border border-danger/30 bg-surface p-4 sm:p-5">
        <h2 className="mb-1 text-sm font-semibold text-danger">
          {sw ? "Eneo la hatari" : "Danger zone"}
        </h2>
        <p className="mb-4 text-xs leading-relaxed text-fg-faint">
          {sw
            ? "Kufuta miradi huondoa gumzo, data, kumbukumbu na faili zote zilizotengenezwa. Hakuna njia ya kurudisha."
            : "Deleting projects removes their chats, datasets, memory and every generated file. There is no way back."}
        </p>
        {wipeResult && <p className="mb-3 text-xs text-fg-muted">{wipeResult}</p>}
        <button
          onClick={() => setConfirmWipe(true)}
          className="inline-flex items-center gap-1.5 rounded-full border border-danger/50 px-3 py-1.5 text-[13px] text-danger transition-colors duration-fast hover:bg-danger-soft"
        >
          <IcoTrash size={13} />
          {sw ? "Futa miradi yote" : "Delete all projects"}
        </button>
      </section>

      <ConfirmDialog
        open={confirmWipe}
        language={lang}
        title={sw ? "Futa MIRADI YOTE?" : "Delete ALL projects?"}
        body={
          sw
            ? "Kila mradi, gumzo, data, kumbukumbu na faili iliyotengenezwa itafutwa kabisa."
            : "Every project, chat, dataset, memory entry and generated file will be permanently deleted."
        }
        confirmLabel={sw ? "Futa yote" : "Delete everything"}
        requirePhrase="DELETE"
        onConfirm={() => void deleteEverything()}
        onCancel={() => setConfirmWipe(false)}
      />
    </div>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border border-border bg-surface p-4 sm:p-5">
      <h2 className="text-sm font-semibold">{title}</h2>
      {note && <p className="mt-1 text-xs leading-relaxed text-fg-faint">{note}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="text-sm">{label}</div>
        {hint && <div className="text-xs text-fg-faint">{hint}</div>}
      </div>
      {children}
    </div>
  );
}

function Info({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex items-start justify-between gap-3 text-sm">
      <span className="flex-shrink-0 text-fg-muted">{label}</span>
      <span className="min-w-0 break-words text-right font-medium">{asText(value)}</span>
    </div>
  );
}

function Segmented({
  value,
  options,
  onChange,
}: {
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
}) {
  return (
    <div className="inline-flex flex-wrap rounded-full border border-border bg-surface-2 p-0.5 text-sm">
      {options.map(([val, label]) => (
        <button
          key={val}
          onClick={() => onChange(val)}
          className={`rounded-full px-3 py-1 transition-colors duration-fast ${
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
      role="switch"
      aria-checked={checked}
      className={`relative h-6 w-11 flex-shrink-0 rounded-full transition-colors duration-fast ${
        checked ? "bg-accent" : "border border-border bg-surface-2"
      }`}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-fast ease-soft ${
          checked ? "left-0.5 translate-x-5" : "left-0.5"
        }`}
      />
    </button>
  );
}
