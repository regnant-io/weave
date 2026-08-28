import { NextRequest, NextResponse } from "next/server";
import { LANG_COOKIE, TOKEN_COOKIE } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

// action=request -> send OTP; action=verify -> verify and sign in.
export async function POST(req: NextRequest) {
  const { action, ...body } = await req.json();

  if (action === "request") {
    const res = await fetch(`${API_BASE}/api/v1/auth/otp/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: body.phone }),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  }

  if (action === "verify") {
    const res = await fetch(`${API_BASE}/api/v1/auth/otp/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: body.phone, code: body.code }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json({ error: data.detail ?? "verification failed" }, { status: res.status });
    }
    const out = NextResponse.json({ user: data.user });
    const secure = process.env.NODE_ENV === "production";
    out.cookies.set(TOKEN_COOKIE, data.access_token, {
      httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 7,
    });
    out.cookies.set(LANG_COOKIE, data.user.preferred_language ?? "sw", { path: "/", maxAge: 60 * 60 * 24 * 365 });
    return out;
  }

  return NextResponse.json({ error: "unknown action" }, { status: 400 });
}
