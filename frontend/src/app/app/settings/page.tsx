import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { getLanguage, getLiteMode, getTheme, isAuthed } from "@/lib/session";
import { t } from "@/lib/i18n";
import PageShell from "@/components/PageShell";
import SettingsClient from "@/components/SettingsClient";
import OllamaSettings from "@/components/OllamaSettings";

export default async function SettingsPage() {
  if (!(await isAuthed())) redirect("/auth/login");
  const [language, theme, lite] = await Promise.all([getLanguage(), getTheme(), getLiteMode()]);

  try {
    const [user, health] = await Promise.all([api.me(), api.health()]);
    return (
      <PageShell>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">{t("settings", language)}</h1>
        <div className="mb-6"><OllamaSettings language={language} /></div>
        <SettingsClient
          language={language}
          theme={theme}
          lite={lite}
          account={{
            phone: user.phone,
            email: user.email,
            role: user.role,
            trust_tier: user.trust_tier,
            phone_verified: user.phone_verified,
          }}
          health={health}
        />
      </PageShell>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) redirect("/auth/login");
    throw e;
  }
}
