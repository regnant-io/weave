import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

/**
 * The signed-in user's own account preferences.
 *
 * Separate from /api/prefs, which writes SSR-readable cookies for things the
 * first paint needs (language, theme, lite mode). These live on the user row in
 * the database instead, because they govern server-side behaviour that has to
 * hold for background jobs too — `allow_source_crawl` decides whether the pages
 * a session consults may be offered as crawl candidates, and a cookie would say
 * nothing to the worker that acts on it.
 */
export async function PATCH(req: NextRequest) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}

export async function GET() {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}
