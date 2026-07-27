/**
 * Service preferences — shared by client and server.
 *
 * Deliberately separate from session.ts: that module imports `next/headers`,
 * which is server-only, so any client component importing a VALUE from it
 * (types are erased, values are not) pulls server code into the browser bundle
 * and fails the build. Constants live here; cookie access stays in session.ts.
 */

/** Capabilities a user can leave switched on for every turn. */
export type ServiceId = "web_search" | "deep_research" | "analysis" | "visuals";

export const ALL_SERVICES: ServiceId[] = ["web_search", "deep_research", "analysis", "visuals"];

export type ServicePrefs = Record<ServiceId, boolean>;

/**
 * Analysis and visuals default ON — they only engage when a turn actually needs
 * them and they cost nothing otherwise. The two web capabilities default OFF:
 * they are slow and bandwidth-hungry, which matters on a metered mobile
 * connection, so the user opts in.
 */
export const DEFAULT_SERVICES: ServicePrefs = {
  web_search: false,
  deep_research: false,
  analysis: true,
  visuals: true,
};

export function parseServices(raw: string | undefined): ServicePrefs {
  if (!raw) return { ...DEFAULT_SERVICES };
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    const out = { ...DEFAULT_SERVICES };
    for (const k of ALL_SERVICES) if (typeof parsed?.[k] === "boolean") out[k] = parsed[k];
    return out;
  } catch {
    return { ...DEFAULT_SERVICES };
  }
}
