import { NextRequest } from "next/server";
import { forward } from "@/lib/backend";

export const runtime = "nodejs";
// Audio is generated per request and never reused.
export const dynamic = "force-dynamic";

/**
 * Streams a line of speech from the FastAPI backend (server/app/routes/tts.py).
 * The audio body is passed through chunk by chunk, and a barge-in that aborts
 * this request also cancels the upstream one.
 */
export async function POST(request: NextRequest) {
  return forward("/api/tts", request);
}
