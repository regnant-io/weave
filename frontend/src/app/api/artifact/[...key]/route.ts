import { NextRequest } from "next/server";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

// Proxy generated artifacts so images and sandboxed iframes load from one origin.
export async function GET(req: NextRequest, ctx: { params: Promise<{ key: string[] }> }) {
  const { key } = await ctx.params;
  const path = key.map(encodeURIComponent).join("/");
  const params = new URL(req.url).searchParams;
  const sig = params.get("sig") ?? "";
  const exp = params.get("exp") ?? "";
  const upstream = await fetch(
    `${API_BASE}/api/v1/artifacts/${path}?exp=${encodeURIComponent(exp)}&sig=${encodeURIComponent(sig)}`,
    { cache: "no-store" },
  );
  if (!upstream.ok || !upstream.body) {
    return new Response("not found", { status: upstream.status });
  }

  const headers = new Headers({
    "Content-Type": upstream.headers.get("Content-Type") ?? "application/octet-stream",
    // The signature is the capability. Shared caches must not retain its body.
    "Cache-Control": "private, max-age=86400",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
  });
  // This is the response-level sandbox that protects direct/new-tab navigation.
  // Dropping it here would preserve iframe isolation while silently removing the
  // same boundary from the external-link button.
  const artifactCsp = upstream.headers.get("Content-Security-Policy");
  if (artifactCsp) headers.set("Content-Security-Policy", artifactCsp);

  return new Response(upstream.body, { status: 200, headers });
}
