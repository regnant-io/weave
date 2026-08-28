import { NextRequest } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

// A single agentic turn can legitimately run for a long time (deep research,
// long analysis). Don't cap it.
export const dynamic = "force-dynamic";
export const maxDuration = 3600;

// Streams the backend's Server-Sent-Events chat response straight through to the
// browser. Proxying here (rather than hitting the backend directly from client
// JS) keeps the auth token in an httpOnly cookie. The stream is passed through
// unbuffered so tokens arrive incrementally on flaky mobile links (architecture
// 4.1).
export async function POST(req: NextRequest, ctx: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await ctx.params;
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const body = await req.json();
  const upstream = await fetch(`${API_BASE}/api/v1/projects/${projectId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ ...body, stream: true }),
  });

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "chat failed");
    return new Response(text, { status: upstream.status });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      // `no-transform` is the part that matters through a tunnel or a CDN: it
      // tells every intermediary (and Next's own compression) not to buffer or
      // re-encode the body. Without it a proxy can hold the stream until it has
      // enough bytes to compress, and the answer arrives in one lump minutes
      // later — which reads as a hang, not as slow streaming.
      "Cache-Control": "no-cache, no-store, no-transform, must-revalidate",
      Connection: "keep-alive",
      // nginx / ngrok / most reverse proxies honour this explicitly.
      "X-Accel-Buffering": "no",
      // Belt and braces: an empty encoding stops Next from gzipping the stream.
      "Content-Encoding": "identity",
    },
  });
}
