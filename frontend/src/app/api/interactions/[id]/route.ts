import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

/**
 * Answer a question the assistant asked mid-turn.
 *
 * A worker thread on the backend is parked waiting for this, so it is on the
 * critical path of a live turn — proxied like the chat stream rather than
 * called directly, to keep the auth token in the httpOnly cookie.
 */
export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const res = await fetch(`${API_BASE}/api/v1/interactions/${encodeURIComponent(id)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: (await req.text().catch(() => "{}")) || "{}",
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}
