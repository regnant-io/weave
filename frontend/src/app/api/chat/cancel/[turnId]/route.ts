import { NextRequest } from "next/server";
import { getToken } from "@/lib/session";

const API_BASE = process.env.WEAVE_API_BASE || "http://127.0.0.1:8000";

/**
 * Stop a running turn.
 *
 * Closing the stream is no longer enough, and that is the point: a turn now
 * survives a dropped connection, so cancelling has to be a deliberate statement
 * rather than a side effect of the socket going away. Without this route,
 * pressing Stop would detach the view and leave the model working.
 */
export async function POST(_req: NextRequest, ctx: { params: Promise<{ turnId: string }> }) {
  const { turnId } = await ctx.params;
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });

  const upstream = await fetch(
    `${API_BASE}/api/v1/turns/${encodeURIComponent(turnId)}/cancel`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` } },
  );
  const text = await upstream.text().catch(() => "");
  return new Response(text || "{}", {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
