import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

/** The project's shared documents. The backend creates one on demand. */
export async function GET(_req: NextRequest, ctx: { params: Promise<{ projectId: string }> }) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const { projectId } = await ctx.params;
  const res = await fetch(`${API_BASE}/api/v1/projects/${projectId}/canvases`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => []), { status: res.status });
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ projectId: string }> }) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const { projectId } = await ctx.params;
  const res = await fetch(`${API_BASE}/api/v1/projects/${projectId}/canvases`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}
