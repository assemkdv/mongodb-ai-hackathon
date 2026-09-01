import { NextRequest } from "next/server";
import { BackendError, forward, listCounterparts } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Turns a free-text description of someone into a stored counterpart.
 * Claude does this in the backend (POST /api/counterparts/generate).
 */
export async function POST(request: NextRequest) {
  return forward("/api/counterparts/generate", request);
}

/**
 * Who you can rehearse against. Proxied rather than called from the browser so
 * the FastAPI backend can stay on localhost and the app keeps one origin.
 */
export async function GET() {
  try {
    const { counterparts } = await listCounterparts();
    return Response.json({ counterparts });
  } catch (err) {
    const status = err instanceof BackendError ? err.status : 502;
    const message = err instanceof Error ? err.message : "Backend unavailable";
    console.error("[counterparts]", message);
    return Response.json({ error: message, counterparts: [] }, { status });
  }
}
