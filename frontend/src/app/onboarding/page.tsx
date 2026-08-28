import { redirect } from "next/navigation";
import { getLanguage, getServices, isAuthed } from "@/lib/session";
import OnboardingClient from "@/components/onboarding/OnboardingClient";

/**
 * Standalone onboarding.
 *
 * Deliberately its own route rather than a modal over the app: a new user has
 * decisions to make (which language they think in, whether they are studying or
 * researching, which capabilities to leave on) and each one changes how every
 * later screen behaves. Full-page gives those choices the weight they deserve
 * and gives us room to actually explain them.
 */
export default async function OnboardingPage() {
  if (!(await isAuthed())) redirect("/auth/login");
  const [language, services] = await Promise.all([getLanguage(), getServices()]);
  return <OnboardingClient initialLanguage={language} initialServices={services} />;
}
