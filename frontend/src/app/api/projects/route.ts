import { NextRequest, NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

export async function GET() {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const res = await fetch(`${API_BASE}/api/v1/projects`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => []), { status: res.status });
}

/**
 * Delete every project.
 *
 * The `?confirm=DELETE` guard is enforced by the backend and forwarded verbatim
 * — a destructive bulk endpoint should not be reachable by a bare DELETE that a
 * stray client retry could trigger, even behind a confirmation modal.
 */
export async function DELETE(req: NextRequest) {
  const token = await getToken();
  if (!token) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const res = await fetch(`${API_BASE}/api/v1/projects${req.nextUrl.search || ""}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}
