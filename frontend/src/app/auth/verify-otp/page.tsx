import { getLanguage } from "@/lib/session";
import { t } from "@/lib/i18n";
import { OtpForm } from "@/components/AuthForms";
import PageShell from "@/components/PageShell";

export default async function VerifyOtpPage() {
  const language = await getLanguage();
  return (
    <PageShell size="narrow">
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">{t("verifyOtp", language)}</h1>
      <p className="mb-5 text-sm text-fg-muted">
        {language === "sw"
          ? "Tutakutumia namba ya siri kwa SMS."
          : "We'll send a one-time code to your phone by SMS."}
      </p>
      <OtpForm language={language} />
    </PageShell>
  );
}
