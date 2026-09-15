import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { REFRESH_COOKIE, TOKEN_COOKIE } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

export async function POST() {
  const store = await cookies();
  const refresh = store.get(REFRESH_COOKIE)?.value;
  if (!refresh) return NextResponse.json({ error: "no refresh session" }, { status: 401 });
  const upstream = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }), cache: "no-store",
  });
  const data = await upstream.json().catch(() => ({}));
  if (!upstream.ok) {
    const out = NextResponse.json({ error: data.detail || "session expired" }, { status: 401 });
    out.cookies.set(TOKEN_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
    out.cookies.set(REFRESH_COOKIE, "", { httpOnly: true, path: "/api/session", maxAge: 0 });
    return out;
  }
  const secure = process.env.NODE_ENV === "production";
  const out = NextResponse.json({ ok: true });
  out.cookies.set(TOKEN_COOKIE, data.access_token, {
    httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 60 * 15,
  });
  out.cookies.set(REFRESH_COOKIE, data.refresh_token, {
    httpOnly: true, secure, sameSite: "strict", path: "/api/session", maxAge: 60 * 60 * 24 * 30,
  });
  return out;
}
