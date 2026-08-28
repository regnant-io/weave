// Session + preference cookies, read server-side (SSR-first, architecture 4.1).
// The auth token is stored httpOnly so client JS can't read it; language, theme,
// service defaults and onboarding state are plain cookies since they must be
// readable during SSR to render the correct first paint.
import { cookies } from "next/headers";
import type { Language } from "./types";
import { parseServices, type ServicePrefs } from "./services";

export const TOKEN_COOKIE = "weave_token";
export const LANG_COOKIE = "weave_lang";
export const MODE_COOKIE = "weave_mode";
export const LITE_COOKIE = "weave_lite";
export const THEME_COOKIE = "weave_theme";
export const SERVICES_COOKIE = "weave_services";
export const ONBOARDED_COOKIE = "weave_onboarded";
export const EFFORT_COOKIE = "weave_effort";

export type ThemePref = "light" | "dark" | "system";

// Service preference constants live in lib/services.ts so client components can
// import them without dragging `next/headers` into the browser bundle.
export {
  ALL_SERVICES,
  DEFAULT_SERVICES,
  parseServices,
  type ServiceId,
  type ServicePrefs,
} from "./services";

export async function getTheme(): Promise<ThemePref> {
  const store = await cookies();
  const v = store.get(THEME_COOKIE)?.value;
  return v === "light" || v === "dark" ? v : "system";
}

export async function getToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(TOKEN_COOKIE)?.value ?? null;
}

export async function getLanguage(): Promise<Language> {
  const store = await cookies();
  const v = store.get(LANG_COOKIE)?.value;
  return v === "en" ? "en" : "sw";
}

export async function getLiteMode(): Promise<boolean> {
  const store = await cookies();
  return store.get(LITE_COOKIE)?.value === "1";
}

export async function getServices(): Promise<ServicePrefs> {
  const store = await cookies();
  return parseServices(store.get(SERVICES_COOKIE)?.value);
}

export async function getEffort(): Promise<string> {
  const store = await cookies();
  const v = store.get(EFFORT_COOKIE)?.value;
  return v === "spool" || v === "weave" || v === "tapestry" ? v : "weave";
}

export async function hasOnboarded(): Promise<boolean> {
  const store = await cookies();
  return store.get(ONBOARDED_COOKIE)?.value === "1";
}

export async function isAuthed(): Promise<boolean> {
  return (await getToken()) !== null;
}
