import { forwardJson } from "@/lib/proxy";

/** Same-origin proxy: record a personal pick. */
export function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/personal-picks");
}
