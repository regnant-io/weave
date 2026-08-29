import { NextRequest } from "next/server";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

// Proxies generated artifacts (charts, decks, PDFs, 3D scenes) from the backend
// so <img>/<iframe> in the chat can load them from the same origin.
export async function GET(req: NextRequest, ctx: { params: Promise<{ key: string[] }> }) {
  const { key } = await ctx.params;
  const path = key.map(encodeURIComponent).join("/");
  const sig = new URL(req.url).searchParams.get("sig") ?? "";
  const upstream = await fetch(
    `${API_BASE}/api/v1/artifacts/${path}?sig=${encodeURIComponent(sig)}`,
    { cache: "no-store" },
  );
  if (!upstream.ok || !upstream.body) {
    return new Response("not found", { status: upstream.status });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/octet-stream",
      // `private`: the signature in the URL is the capability that authorises
      // this artifact, so a shared cache holding the response would be storing
      // one user's generated work under a key anyone with the URL can replay.
      "Cache-Control": "private, max-age=86400",
    },
  });
}
