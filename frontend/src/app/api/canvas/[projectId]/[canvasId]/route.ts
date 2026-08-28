import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

async function forward(req: NextRequest, projectId: string, canvasId: string, method: string) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const init: RequestInit = {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    cache: "no-store",
  };
  if (method === "PUT") init.body = await req.text();
  const res = await fetch(
    `${API_BASE}/api/v1/projects/${projectId}/canvases/${canvasId}`,
    init,
  );
  // The 409 body carries the current document so the editor can show the
  // divergence — it must reach the client intact rather than being flattened
  // into a generic error.
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}

export async function GET(req: NextRequest,
                          ctx: { params: Promise<{ projectId: string; canvasId: string }> }) {
  const { projectId, canvasId } = await ctx.params;
  return forward(req, projectId, canvasId, "GET");
}

export async function PUT(req: NextRequest,
                          ctx: { params: Promise<{ projectId: string; canvasId: string }> }) {
  const { projectId, canvasId } = await ctx.params;
  return forward(req, projectId, canvasId, "PUT");
}

export async function DELETE(req: NextRequest,
                             ctx: { params: Promise<{ projectId: string; canvasId: string }> }) {
  const { projectId, canvasId } = await ctx.params;
  return forward(req, projectId, canvasId, "DELETE");
}
