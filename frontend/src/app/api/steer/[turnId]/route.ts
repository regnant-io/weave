import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

/**
 * Redirect a turn that is still running.
 *
 * Kept deliberately thin and uncached: the value of a redirect is entirely in
 * how fast it lands, and anything that buffers it defeats the point.
 */
export async function POST(req: NextRequest, ctx: { params: Promise<{ turnId: string }> }) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const { turnId } = await ctx.params;
  const res = await fetch(`${API_BASE}/api/v1/steer/${encodeURIComponent(turnId)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}
