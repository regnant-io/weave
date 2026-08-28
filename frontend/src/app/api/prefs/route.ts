import { NextRequest, NextResponse } from "next/server";
import {
  EFFORT_COOKIE,
  LANG_COOKIE,
  LITE_COOKIE,
  MODE_COOKIE,
  ONBOARDED_COOKIE,
  SERVICES_COOKIE,
  THEME_COOKIE,
} from "@/lib/session";
import { ALL_SERVICES } from "@/lib/services";

// Persist UI preferences as SSR-readable cookies so the very first
// server-rendered paint already reflects the choice.
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const { language, mode, lite, theme, services, effort, onboarded } = body ?? {};
  const out = NextResponse.json({ ok: true });
  const year = 60 * 60 * 24 * 365;
  const opts = { path: "/", maxAge: year } as const;

  if (language === "sw" || language === "en") out.cookies.set(LANG_COOKIE, language, opts);
  if (mode === "student" || mode === "researcher") out.cookies.set(MODE_COOKIE, mode, opts);
  if (typeof lite === "boolean") out.cookies.set(LITE_COOKIE, lite ? "1" : "0", opts);
  if (theme === "light" || theme === "dark" || theme === "system") {
    out.cookies.set(THEME_COOKIE, theme, opts);
  }
  if (effort === "spool" || effort === "weave" || effort === "tapestry") {
    out.cookies.set(EFFORT_COOKIE, effort, opts);
  }
  if (typeof onboarded === "boolean") {
    out.cookies.set(ONBOARDED_COOKIE, onboarded ? "1" : "0", opts);
  }
  if (services && typeof services === "object") {
    // Whitelist keys so a stray client payload can't bloat the cookie.
    const clean: Record<string, boolean> = {};
    for (const k of ALL_SERVICES) if (typeof services[k] === "boolean") clean[k] = services[k];
    out.cookies.set(SERVICES_COOKIE, encodeURIComponent(JSON.stringify(clean)), opts);
  }
  return out;
}
