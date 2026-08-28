import { NextResponse } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

export async function GET() {
  const token = await getToken();
  if (!token) return NextResponse.json({}, { status: 401 });
  const res = await fetch(`${API_BASE}/api/v1/stats`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
}
