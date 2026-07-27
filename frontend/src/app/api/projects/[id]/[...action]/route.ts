import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

async function proxy(req: NextRequest, id: string, action: string[], method: string) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const init: RequestInit = {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    cache: "no-store",
  };
  if (method === "POST" || method === "PATCH") init.body = await req.text().catch(() => "{}") || "{}";
  const res = await fetch(`${API_BASE}/api/v1/projects/${id}/${action.join("/")}`, init);
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string; action: string[] }> }) {
  const { id, action } = await ctx.params;
  return proxy(req, id, action, "POST");
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string; action: string[] }> }) {
  const { id, action } = await ctx.params;
  return proxy(req, id, action, "PATCH");
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ id: string; action: string[] }> }) {
  const { id, action } = await ctx.params;
  return proxy(req, id, action, "DELETE");
}
