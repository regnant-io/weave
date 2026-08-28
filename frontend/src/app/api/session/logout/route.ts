import { NextResponse } from "next/server";
import { TOKEN_COOKIE } from "@/lib/session";

export async function POST() {
  const out = NextResponse.json({ ok: true });
  out.cookies.set(TOKEN_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  return out;
}
