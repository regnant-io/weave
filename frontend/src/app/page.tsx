import Link from "next/link";
import { redirect } from "next/navigation";
import { getLanguage, isAuthed } from "@/lib/session";
import { t } from "@/lib/i18n";
import PageShell from "@/components/PageShell";

// Landing + mode selection. Fully server-rendered (paints on throttled 3G).
export default async function LandingPage() {
  if (await isAuthed()) redirect("/app/projects");
  const language = await getLanguage();

  return (
    <PageShell>
      <section className="py-10 text-center xs:py-16">
        <div className="mx-auto mb-5 grid h-14 w-14 place-items-center bg-accent text-xl font-bold text-accent-fg">
          W
        </div>
        <h1 className="text-3xl font-semibold tracking-tight xs:text-4xl">Weave</h1>
        <p className="mx-auto mt-3 max-w-md text-base text-fg-muted xs:text-lg">{t("appTagline", language)}</p>
      </section>

      <h2 className="mb-4 text-center text-sm font-medium uppercase tracking-wide text-fg-faint">
        {t("chooseMode", language)}
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <ModeCard href="/auth/register?mode=student" title={t("student", language)} desc={t("studentDesc", language)} />
        <ModeCard href="/auth/register?mode=researcher" title={t("researcher", language)} desc={t("researcherDesc", language)} accent />
      </div>

      <div className="mt-8 border border-border bg-surface p-4 text-sm text-fg-muted">
        <p className="mb-2 font-medium text-fg">{language === "sw" ? "Jaribu bila kujisajili" : "Try without signing up"}</p>
        <Link href="/app/library" className="text-accent hover:underline">
          {t("searchLibrary", language)} →
        </Link>
      </div>

      <p className="mt-6 text-center text-sm text-fg-muted">
        {t("haveAccount", language)}{" "}
        <Link href="/auth/login" className="text-accent hover:underline">{t("login", language)}</Link>
      </p>
    </PageShell>
  );
}

function ModeCard({ href, title, desc, accent }: { href: string; title: string; desc: string; accent?: boolean }) {
  return (
    <Link
      href={href}
      className="group block border border-border bg-surface p-5 transition-all hover:-translate-y-0.5 hover:border-border-strong hover:shadow-soft"
    >
      <span className={`mb-3 inline-block h-2.5 w-2.5 rounded-full ${accent ? "bg-warn" : "bg-accent"}`} />
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-1 text-sm text-fg-muted">{desc}</p>
      <span className="mt-3 inline-block text-sm text-accent opacity-0 transition-opacity group-hover:opacity-100">→</span>
    </Link>
  );
}
