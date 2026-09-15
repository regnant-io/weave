import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { REFRESH_COOKIE, TOKEN_COOKIE } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

export async function POST() {
  const store = await cookies();
  const token = store.get(TOKEN_COOKIE)?.value;
  const refresh = store.get(REFRESH_COOKIE)?.value;
  if (token || refresh) {
    await fetch(`${API_BASE}/api/v1/auth/logout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ refresh_token: refresh ?? null }),
    }).catch(() => undefined);
  }
  const out = NextResponse.json({ ok: true });
  out.cookies.set(TOKEN_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  out.cookies.set(REFRESH_COOKIE, "", { httpOnly: true, path: "/api/session", maxAge: 0 });
  return out;
}
