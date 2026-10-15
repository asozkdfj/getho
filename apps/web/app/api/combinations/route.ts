import { apiBaseUrl } from "@/lib/config";

/**
 * Same-origin proxy for the browser -> FastAPI combination call.
 * Keeps the API host private (no CORS / public API URL needed) and forwards
 * only this single endpoint.
 */
export async function POST(request: Request): Promise<Response> {
  let body: string;
  try {
    body = JSON.stringify(await request.json());
  } catch {
    return Response.json({ detail: "invalid JSON body" }, { status: 400 });
  }
  try {
    const upstream = await fetch(`${apiBaseUrl()}/combinations/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json({ detail: "analysis service unavailable" }, { status: 502 });
  }
}
