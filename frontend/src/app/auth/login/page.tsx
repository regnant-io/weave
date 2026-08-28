import Link from "next/link";
import { getLanguage } from "@/lib/session";
import { t } from "@/lib/i18n";
import { LoginForm } from "@/components/AuthForms";
import PageShell from "@/components/PageShell";

export default async function LoginPage() {
  const language = await getLanguage();
  return (
    <PageShell size="narrow">
      <h1 className="mb-5 text-2xl font-semibold tracking-tight">{t("login", language)}</h1>
      <LoginForm language={language} />
      <p className="mt-4 text-center text-sm text-fg-muted">
        <Link href="/auth/verify-otp" className="text-accent hover:underline">
          {language === "sw" ? "Ingia kwa namba ya siri (OTP)" : "Sign in with an OTP code"}
        </Link>
      </p>
    </PageShell>
  );
}
