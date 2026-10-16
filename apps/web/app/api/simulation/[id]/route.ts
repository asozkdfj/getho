import { apiBaseUrl } from "@/lib/config";

/** Same-origin proxy for the browser -> FastAPI simulation call (this endpoint only). */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  if (!/^\d+$/.test(id)) {
    return Response.json({ detail: "invalid fixture id" }, { status: 400 });
  }
  const incoming = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of ["runs", "seed"]) {
    const value = incoming.get(key);
    if (value !== null && /^\d+$/.test(value)) query.set(key, value);
  }
  try {
    const upstream = await fetch(`${apiBaseUrl()}/fixtures/${id}/simulation?${query.toString()}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json({ detail: "simulation service unavailable" }, { status: 502 });
  }
}
