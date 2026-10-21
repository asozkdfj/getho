import { apiBaseUrl } from "./config";

/**
 * Forward one JSON POST from the browser to the API (same origin: the API host
 * stays private). The body is re-serialised so only valid JSON goes through.
 */
export async function forwardJson(request: Request, path: string): Promise<Response> {
  let body: string;
  try {
    body = JSON.stringify(await request.json());
  } catch {
    return Response.json({ detail: "invalid JSON body" }, { status: 400 });
  }
  try {
    const upstream = await fetch(`${apiBaseUrl()}${path}`, {
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
    return Response.json({ detail: "service unavailable" }, { status: 502 });
  }
}

/** Pick ids are UUIDs made by the API; anything else never reaches it. */
export const PICK_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
