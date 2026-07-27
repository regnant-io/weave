import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

// Proxies a multipart dataset upload to the backend, forwarding an idempotency
// key (architecture 5.2) so a retried upload on a flaky connection is deduped.
export async function POST(req: NextRequest, ctx: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await ctx.params;
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });

  const form = await req.formData();
  const idempotencyKey = req.headers.get("Idempotency-Key") ?? crypto.randomUUID();

  const upstream = await fetch(`${API_BASE}/api/v1/projects/${projectId}/datasets`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Idempotency-Key": idempotencyKey },
    body: form,
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
