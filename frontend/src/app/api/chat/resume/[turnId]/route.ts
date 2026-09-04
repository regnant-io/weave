import { NextRequest } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

export const dynamic = "force-dynamic";
export const maxDuration = 3600;

/**
 * Reattach to a turn that is still running on the server.
 *
 * The turn is not owned by the connection that started it (see the backend's
 * orchestration/live.py), so a dropped stream is a lost VIEW rather than lost
 * work. This route is how the client gets the view back: `?after=<seq>` is the
 * sequence number of the last event it actually received, and the server
 * replays from the next one.
 *
 * A 404 here is a real answer, not a failure to handle: the live registry is
 * per-process, so a reconnect that lands on a different worker cannot be
 * served. The client treats it as "reload the thread instead", which is
 * correct, because a turn that finished is in the database.
 */
export async function GET(req: NextRequest, ctx: { params: Promise<{ turnId: string }> }) {
  const { turnId } = await ctx.params;
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const after = req.nextUrl.searchParams.get("after") ?? "-1";
  const upstream = await fetch(
    `${API_BASE}/api/v1/turns/${encodeURIComponent(turnId)}/stream?after=${encodeURIComponent(after)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "resume failed");
    return new Response(text, { status: upstream.status });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      // Same reasoning as the POST route: `no-transform` is what stops an
      // intermediary buffering the stream until it has enough to compress.
      "Cache-Control": "no-cache, no-store, no-transform, must-revalidate",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
      "Content-Encoding": "identity",
    },
  });
}
