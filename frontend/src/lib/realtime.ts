/**
 * Opening a Weave WebSocket from the browser.
 *
 * Sockets connect to the API origin rather than to Next (route handlers proxy
 * HTTP, not upgrades), and they authenticate with a short-lived socket-scoped
 * ticket rather than the session cookie. `/api/realtime` hands back both in one
 * call; this wraps that so no component has to know either fact.
 */

export type RealtimeConfig = { wsBase: string; token: string; expiresIn: number };

/** A ticket is only good for a minute, so it is fetched per connection. */
export async function realtimeConfig(): Promise<RealtimeConfig | null> {
  try {
    const res = await fetch("/api/realtime", { cache: "no-store" });
    if (!res.ok) return null;
    const body = await res.json();
    if (!body?.token || !body?.wsBase) return null;
    return body as RealtimeConfig;
  } catch {
    return null;
  }
}

/** Build a socket URL for `path` (which must start with "/"). */
export function socketUrl(config: RealtimeConfig, path: string): string {
  const base = config.wsBase.replace(/\/+$/, "");
  return `${base}/api/v1${path}?token=${encodeURIComponent(config.token)}`;
}

/**
 * Open a socket, fetching a fresh ticket first.
 *
 * Returns null when there is no session or the API is unreachable — callers
 * treat that as "this feature is unavailable right now" rather than an error,
 * because both voice and the canvas are additive to a working chat.
 */
export async function openSocket(path: string): Promise<WebSocket | null> {
  const config = await realtimeConfig();
  if (!config) return null;
  try {
    return new WebSocket(socketUrl(config, path));
  } catch {
    return null;
  }
}
