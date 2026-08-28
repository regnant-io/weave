import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

async function proxy(req: NextRequest, path: string[], method: string) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const qs = new URL(req.url).search;
  const init: RequestInit = {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    cache: "no-store",
  };
  // PATCH and PUT carry bodies too. The crawler admin edits seed budgets and
  // approves session-discovered seeds over PATCH, and forwarding only POST
  // bodies would turn every one of those edits into a silent no-op.
  if (method === "POST" || method === "PATCH" || method === "PUT") {
    init.body = await req.text();
  }
  const res = await fetch(`${API_BASE}/api/v1/admin/${path.join("/")}${qs}`, init);
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path, "GET");
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path, "POST");
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path, "PATCH");
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path, "DELETE");
}
