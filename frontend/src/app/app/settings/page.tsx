import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import {
  getEffort,
  getLanguage,
  getLiteMode,
  getServices,
  getTheme,
  isAuthed,
} from "@/lib/session";
import { t } from "@/lib/i18n";
import type { Effort } from "@/lib/types";
import PageShell from "@/components/PageShell";
import SettingsClient from "@/components/SettingsClient";
import OllamaSettings from "@/components/OllamaSettings";

export default async function SettingsPage() {
  if (!(await isAuthed())) redirect("/auth/login");
  const [language, theme, lite, effort, services] = await Promise.all([
    getLanguage(),
    getTheme(),
    getLiteMode(),
    getEffort(),
    getServices(),
  ]);

  try {
    // `me` is the only call that must succeed — everything else degrades to a
    // quieter panel rather than taking the whole page down. That is the lesson
    // from the React #31 crash: settings is where you go when something is
    // wrong, so it has to render when things are wrong.
    const user = await api.me();
    const [health, workspace, models] = await Promise.all([
      api.health(),
      api.workspaceStatus(),
      api.models(),
    ]);

    const currentModel = models?.current_model ?? "";
    const contextWindow =
      models?.models?.find((m) => m.name === currentModel)?.context ??
      models?.num_ctx_fallback ??
      0;

    return (
      <PageShell>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">{t("settings", language)}</h1>
        <div className="mb-6">
          <OllamaSettings language={language} />
        </div>
        <SettingsClient
          language={language}
          theme={theme}
          lite={lite}
          effort={effort as Effort}
          services={services}
          account={{
            phone: user.phone,
            email: user.email,
            role: user.role,
            trust_tier: user.trust_tier,
            phone_verified: user.phone_verified,
          }}
          health={health}
          workspace={workspace}
          contextWindow={contextWindow}
          currentModel={currentModel}
        />
      </PageShell>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/auth/login");
    throw e;
  }
}
