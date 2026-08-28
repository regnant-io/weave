import { NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

/**
 * Everything the browser needs to open a Weave WebSocket, in one call.
 *
 * WHY THE BROWSER TALKS TO THE BACKEND DIRECTLY
 * Next.js route handlers proxy HTTP; they do not carry a WebSocket upgrade. So
 * sockets connect to the API origin rather than to Next, and the client has to
 * be told where that is — hence `wsBase`, resolved from the environment here so
 * the deployment topology stays server-side.
 *
 * WHY THE TOKEN IS NOT THE SESSION TOKEN
 * The session lives in an httpOnly cookie so page scripts cannot read it. A
 * socket credential has to be readable by scripts (it goes in the query string),
 * so handing out the session token would erase that protection. This returns a
 * sixty-second, socket-scoped ticket the REST API refuses outright.
 */
export async function GET() {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const res = await fetch(`${API_BASE}/api/v1/ws-ticket`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    return NextResponse.json({ error: "could not mint a socket ticket" }, { status: res.status });
  }
  const body = await res.json().catch(() => ({}));

  // Default to the port docker-compose publishes the backend on, so a local
  // `docker compose up` works with no extra configuration.
  const wsBase = process.env.WEAVE_PUBLIC_WS_BASE || "ws://localhost:8001";

  return NextResponse.json(
    { wsBase, token: body.token, expiresIn: body.expires_in ?? 60 },
    { headers: { "Cache-Control": "no-store" } },
  );
}
