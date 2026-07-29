"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { Language, Mode } from "@/lib/types";
import type { ServiceId, ServicePrefs } from "@/lib/services";
import WeaveMark from "@/components/brand/WeaveMark";
import {
  IcoArrowUp,
  IcoChart,
  IcoCheck,
  IcoGlobe,
  IcoTelescope,
  IcoTerminal,
} from "@/components/ui/icons";

type StepId = "language" | "mode" | "field" | "services" | "project";
const STEPS: StepId[] = ["language", "mode", "field", "services", "project"];

const FIELDS: { id: string; sw: string; en: string }[] = [
  { id: "health", sw: "Afya na tiba", en: "Health & medicine" },
  { id: "agriculture", sw: "Kilimo", en: "Agriculture" },
  { id: "economics", sw: "Uchumi na biashara", en: "Economics & business" },
  { id: "education", sw: "Elimu", en: "Education" },
  { id: "engineering", sw: "Uhandisi na teknolojia", en: "Engineering & tech" },
  { id: "environment", sw: "Mazingira", en: "Environment & climate" },
  { id: "social", sw: "Sayansi ya jamii", en: "Social sciences" },
  { id: "natural", sw: "Sayansi asilia", en: "Natural sciences" },
];

const SERVICE_META: {
  id: ServiceId;
  icon: any;
  sw: [string, string];
  en: [string, string];
  cost: [string, string];
}[] = [
  {
    id: "web_search",
    icon: IcoGlobe,
    en: ["Web search", "Look things up on the live web when the library has no answer."],
    sw: ["Utafutaji mtandaoni", "Tafuta mtandaoni pale maktaba haina jibu."],
    cost: ["Polepole kidogo", "Slightly slower"],
  },
  {
    id: "deep_research",
    icon: IcoTelescope,
    en: ["Deep research", "Read many sources end to end and cite them. Best for literature reviews."],
    sw: ["Utafiti wa kina", "Soma vyanzo vingi kikamilifu na uvitaje. Bora kwa mapitio ya maandiko."],
    cost: ["Dakika kadhaa", "Takes minutes"],
  },
  {
    id: "analysis",
    icon: IcoTerminal,
    en: ["Data analysis", "Run real Python over datasets you upload, in a sandbox."],
    sw: ["Uchambuzi wa data", "Endesha Python halisi kwenye data yako, kwenye sandbox."],
    cost: ["", ""],
  },
  {
    id: "visuals",
    icon: IcoChart,
    en: ["Visuals", "Charts, diagrams, interactive simulations and 3D you can explore."],
    sw: ["Taswira", "Chati, michoro, uigaji shirikishi na 3D unayoweza kuchunguza."],
    cost: ["", ""],
  },
];

export default function OnboardingClient({
  initialLanguage,
  initialServices,
}: {
  initialLanguage: Language;
  initialServices: ServicePrefs;
}) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [language, setLanguage] = useState<Language>(initialLanguage);
  const [mode, setMode] = useState<Mode>("student");
  const [field, setField] = useState<string>("");
  const [services, setServices] = useState<ServicePrefs>(initialServices);
  const [projectTitle, setProjectTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const sw = language === "sw";
  const id = STEPS[step];

  const heading = useMemo<Record<StepId, [string, string]>>(
    () => ({
      language: ["Lugha yako", "Your language"],
      mode: ["Unafanya nini?", "What are you here to do?"],
      field: ["Eneo lako", "Your field"],
      services: ["Uwezo", "Capabilities"],
      project: ["Mradi wa kwanza", "Your first project"],
    }),
    [],
  );

  const blurb: Record<StepId, [string, string]> = {
    language: [
      "Weave inafanya kazi kwa Kiswahili na Kiingereza kikamilifu. Unaweza kubadilisha wakati wowote.",
      "Weave works fully in both Kiswahili and English. You can switch at any time, mid-conversation.",
    ],
    mode: [
      "Hii inabadilisha jinsi Weave inavyojibu — si kile inachojua.",
      "This changes how Weave answers you — not what it knows.",
    ],
    field: [
      "Hutumika kuchagua vyanzo na mifano inayokufaa. Si lazima.",
      "Used to pick sources and examples that fit your work. Optional.",
    ],
    services: [
      "Washa zile unazotaka zitumike kila wakati. Weave bado itazitumia inapohitajika.",
      "Switch on what you want used by default. Weave will still reach for the others when a question needs them.",
    ],
    project: [
      "Kila kitu kinaishi ndani ya mradi — mazungumzo, data, dhana, na taswira.",
      "Everything lives inside a project — conversations, datasets, hypotheses, and visuals.",
    ],
  };

  async function savePrefs(patch: Record<string, unknown>) {
    await fetch("/api/prefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).catch(() => {});
  }

  function next() {
    if (step < STEPS.length - 1) setStep(step + 1);
  }
  function back() {
    if (step > 0) setStep(step - 1);
  }

  async function finish() {
    setBusy(true);
    setError("");
    try {
      await savePrefs({ language, mode, services, onboarded: true });
      const title =
        projectTitle.trim() ||
        (sw ? "Mradi wangu wa kwanza" : "My first project");
      const res = await fetch("/api/projects/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, mode }),
      });
      if (!res.ok) throw new Error(await res.text().catch(() => "could not create project"));
      const data = await res.json().catch(() => ({}));
      const pid = data?.id ?? data?.project?.id;
      router.push(pid ? `/app/chat/${pid}` : "/app/projects");
      router.refresh();
    } catch (e) {
      // Onboarding must never trap the user. If project creation fails we still
      // saved their preferences, so let them into the app and surface why.
      setError(
        (sw ? "Imeshindikana kuunda mradi: " : "Could not create the project: ") +
          (e as Error).message,
      );
      setBusy(false);
    }
  }

  const canAdvance = id !== "field" || true;

  return (
    <div className="tx-noise min-h-app relative">
      <div className="min-h-app relative z-[1] mx-auto flex w-full max-w-3xl flex-col px-5 py-10 md:px-8">
        {/* brand + progress */}
        <div className="flex items-center justify-between">
          <WeaveMark size="sm" className="text-fg" />
          <div className="flex items-center gap-1.5">
            {STEPS.map((s, i) => (
              <span
                key={s}
                aria-hidden
                className={`h-[2px] transition-all duration-slow ease-expo ${
                  i === step ? "w-7 bg-accent" : i < step ? "w-4 bg-fg-faint" : "w-4 bg-border"
                }`}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-1 flex-col justify-center py-12">
          <div key={id} className="animate-rise">
            <div className="eyebrow mb-3">
              {String(step + 1).padStart(2, "0")} / {String(STEPS.length).padStart(2, "0")}
            </div>
            <h1 className="display text-4xl md:text-5xl">
              {sw ? heading[id][0] : heading[id][1]}
            </h1>
            <p className="mt-3 max-w-xl font-read text-[15.5px] leading-relaxed text-fg-muted">
              {sw ? blurb[id][0] : blurb[id][1]}
            </p>

            <div className="mt-8">
              {id === "language" && (
                <div className="grid gap-3 sm:grid-cols-2">
                  {(
                    [
                      ["sw", "Kiswahili", "Nitaandika na kusoma kwa Kiswahili"],
                      ["en", "English", "I'll read and write in English"],
                    ] as const
                  ).map(([code, label, hint]) => (
                    <Choice
                      key={code}
                      selected={language === code}
                      onClick={() => {
                        setLanguage(code as Language);
                        savePrefs({ language: code });
                      }}
                      title={label}
                      hint={hint}
                    />
                  ))}
                </div>
              )}

              {id === "mode" && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Choice
                    selected={mode === "student"}
                    onClick={() => setMode("student")}
                    title={sw ? "Mwanafunzi" : "Student"}
                    hint={
                      sw
                        ? "Mwongozo hatua kwa hatua. Weave itakuuliza maswali badala ya kukupa majibu ya moja kwa moja."
                        : "Guided, step by step. Weave asks you questions rather than handing over finished answers."
                    }
                  />
                  <Choice
                    selected={mode === "researcher"}
                    onClick={() => setMode("researcher")}
                    title={sw ? "Mtafiti" : "Researcher"}
                    hint={
                      sw
                        ? "Majibu ya moja kwa moja, uchambuzi wa data, na rejea kali."
                        : "Direct answers, real data analysis, and strict citations."
                    }
                  />
                </div>
              )}

              {id === "field" && (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {FIELDS.map((f) => (
                    <button
                      key={f.id}
                      onClick={() => setField(field === f.id ? "" : f.id)}
                      className={`border px-3 py-2.5 text-left text-sm transition-all duration-fast ease-soft ${
                        field === f.id
                          ? "border-accent bg-accent-soft text-fg"
                          : "border-border text-fg-muted hover:border-border-mid hover:text-fg"
                      }`}
                    >
                      {sw ? f.sw : f.en}
                    </button>
                  ))}
                </div>
              )}

              {id === "services" && (
                <div className="grid gap-2">
                  {SERVICE_META.map((s) => {
                    const Icon = s.icon;
                    const on = services[s.id];
                    const [label, desc] = sw ? s.sw : s.en;
                    const cost = sw ? s.cost[0] : s.cost[1];
                    return (
                      <button
                        key={s.id}
                        onClick={() => setServices({ ...services, [s.id]: !on })}
                        className={`flex items-start gap-3 border px-4 py-3 text-left transition-all duration-fast ease-soft ${
                          on ? "border-accent-line bg-accent-soft" : "border-border hover:border-border-mid"
                        }`}
                      >
                        <Icon size={18} className={`mt-0.5 ${on ? "text-accent" : "text-fg-faint"}`} />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-baseline gap-2">
                            <span className="text-sm font-medium text-fg">{label}</span>
                            {cost && <span className="eyebrow">{cost}</span>}
                          </span>
                          <span className="mt-0.5 block font-read text-[13px] leading-relaxed text-fg-muted">
                            {desc}
                          </span>
                        </span>
                        <span
                          className={`mt-1 grid h-4 w-4 flex-shrink-0 place-items-center border transition-colors duration-fast ${
                            on ? "border-accent bg-accent text-accent-fg" : "border-border-mid"
                          }`}
                        >
                          {on && <IcoCheck size={11} strokeWidth={2.5} />}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {id === "project" && (
                <div>
                  <label className="eyebrow mb-2 block">
                    {sw ? "Jina la mradi" : "Project name"}
                  </label>
                  <input
                    value={projectTitle}
                    onChange={(e) => setProjectTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !busy) finish();
                    }}
                    autoFocus
                    placeholder={
                      sw
                        ? "k.m. Athari za mvua kwenye mavuno ya mahindi"
                        : "e.g. Rainfall and maize yield in Iringa"
                    }
                    className="w-full border-b-2 border-border bg-transparent px-0 py-2.5 font-read text-lg outline-none transition-colors duration-fast placeholder:italic placeholder:text-fg-faint focus:border-accent"
                  />
                  <p className="mt-3 text-[13px] text-fg-faint">
                    {sw
                      ? "Unaweza kubadilisha baadaye, na kuunda miradi mingi."
                      : "You can rename it later, and create as many projects as you like."}
                  </p>
                  {error && (
                    <p className="mt-4 border-l-2 border-danger bg-danger-soft px-3 py-2 text-[13px] text-danger">
                      {error}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* nav */}
        <div className="flex items-center gap-3 border-t border-border pt-5">
          {step > 0 && (
            <button
              onClick={back}
              className="text-[11px] uppercase tracking-widest text-fg-muted transition-colors duration-fast hover:text-fg"
            >
              {sw ? "Rudi" : "Back"}
            </button>
          )}
          <button
            onClick={() => {
              savePrefs({ onboarded: true });
              router.push("/app/projects");
            }}
            className="ml-auto text-[11px] uppercase tracking-widest text-fg-faint transition-colors duration-fast hover:text-fg"
          >
            {sw ? "Ruka" : "Skip"}
          </button>
          {id === "project" ? (
            <button
              onClick={finish}
              disabled={busy}
              className="inline-flex items-center gap-2 bg-accent px-5 py-2.5 text-[11px] uppercase tracking-widest text-accent-fg transition-all duration-fast ease-soft hover:bg-accent-strong active:scale-[.98] disabled:opacity-50"
            >
              {busy ? (sw ? "Inaanza…" : "Starting…") : sw ? "Anza" : "Start"}
              <IcoArrowUp size={13} className="rotate-90" strokeWidth={2} />
            </button>
          ) : (
            <button
              onClick={next}
              disabled={!canAdvance}
              className="inline-flex items-center gap-2 bg-fg px-5 py-2.5 text-[11px] uppercase tracking-widest text-bg transition-all duration-fast ease-soft hover:opacity-85 active:scale-[.98]"
            >
              {sw ? "Endelea" : "Continue"}
              <IcoArrowUp size={13} className="rotate-90" strokeWidth={2} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Choice({
  selected,
  onClick,
  title,
  hint,
}: {
  selected: boolean;
  onClick: () => void;
  title: string;
  hint: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`group relative border p-5 text-left transition-all duration-fast ease-soft ${
        selected
          ? "border-accent bg-accent-soft"
          : "border-border hover:border-border-mid hover:bg-surface-2"
      }`}
    >
      <span className="flex items-center justify-between">
        <span className="display text-xl">{title}</span>
        <span
          className={`grid h-4 w-4 flex-shrink-0 place-items-center border transition-colors duration-fast ${
            selected ? "border-accent bg-accent text-accent-fg" : "border-border-mid"
          }`}
        >
          {selected && <IcoCheck size={11} strokeWidth={2.5} />}
        </span>
      </span>
      <span className="mt-2 block font-read text-[13.5px] leading-relaxed text-fg-muted">{hint}</span>
    </button>
  );
}
