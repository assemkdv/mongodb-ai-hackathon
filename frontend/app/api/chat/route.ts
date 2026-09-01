import { NextRequest } from "next/server";
import { forward } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * One rehearsal turn. The voice agent itself lives in the FastAPI backend
 * (server/app/routes/turn.py); this route only forwards to it, so the
 * browser talks to a single origin and never sees an API key.
 */
export async function POST(request: NextRequest) {
  return forward("/api/turn", request);
}
