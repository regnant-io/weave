import { getLanguage } from "@/lib/session";
import { t } from "@/lib/i18n";
import { RegisterForm } from "@/components/AuthForms";
import PageShell from "@/components/PageShell";
import type { Mode } from "@/lib/types";

export default async function RegisterPage({ searchParams }: { searchParams: Promise<{ mode?: string }> }) {
  const language = await getLanguage();
  const { mode } = await searchParams;
  const initialMode: Mode = mode === "researcher" ? "researcher" : "student";
  return (
    <PageShell size="narrow">
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">{t("register", language)}</h1>
      <p className="mb-5 text-sm text-fg-muted">{t("chooseMode", language)}</p>
      <RegisterForm language={language} initialMode={initialMode} />
    </PageShell>
  );
}
