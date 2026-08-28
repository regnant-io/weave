import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

// Truncate the conversation from a message onward (used by edit-and-resend).
export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ projectId: string; messageId: string }> }) {
  const { projectId, messageId } = await ctx.params;
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const res = await fetch(`${API_BASE}/api/v1/projects/${projectId}/messages/from/${messageId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}
