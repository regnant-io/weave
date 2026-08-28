import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

/**
 * Project-level CRUD (rename / change mode / delete).
 *
 * Sibling to [...action], which handles everything UNDER a project. This file
 * exists because Next's catch-all requires at least one path segment, so
 * `/api/projects/:id` with no action would otherwise 404.
 */
async function proxy(req: NextRequest, id: string, method: string) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const init: RequestInit = {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    cache: "no-store",
  };
  if (method === "PATCH") init.body = (await req.text().catch(() => "{}")) || "{}";
  const res = await fetch(
    `${API_BASE}/api/v1/projects/${encodeURIComponent(id)}${req.nextUrl.search || ""}`,
    init,
  );
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  return proxy(req, (await ctx.params).id, "GET");
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  return proxy(req, (await ctx.params).id, "PATCH");
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  return proxy(req, (await ctx.params).id, "DELETE");
}
