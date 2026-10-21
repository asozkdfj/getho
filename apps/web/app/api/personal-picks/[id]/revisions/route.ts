import { PICK_ID, forwardJson } from "@/lib/proxy";

/** Same-origin proxy: store a new revision of a personal pick. */
export async function POST(
  request: Request,
  ctx: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await ctx.params;
  if (!PICK_ID.test(id)) return Response.json({ detail: "pick not found" }, { status: 404 });
  return forwardJson(request, `/personal-picks/${id}/revisions`);
}
