/**
 * Client for the FastAPI backend (server/).
 *
 * Only the Next.js route layer talks to this, never the browser. That keeps
 * one origin for the app, keeps every API key on the server, and lets the
 * backend stay on localhost in development.
 */

const BASE = process.env.BACKEND_URL || "http://localhost:3001";

export interface Counterpart {
  _id: string;
  name: string;
  role: string;
  scenario: string;
  /** Who *you* are in this scene, e.g. "his tenant of four years". */
  userRole?: string;
  wants: string;
  concessions: string[];
  boundaries: string[];
  escalation: string;
  speechRules: {
    maximumWords: number;
    fragmentsWhenTense: boolean;
    usesFiller: boolean;
  };
}

/** Summary shape returned by the list endpoint. */
export interface CounterpartSummary {
  _id: string;
  name: string;
  role: string;
  scenario: string;
  userRole?: string;
  activeTraits: number;
}

export interface Trait {
  _id: string;
  counterpartId: string;
  category: string;
  claim: string;
  confidence: number;
  status: "active" | "superseded";
  version: number;
  evidenceIds: string[];
  supersedes?: string;
}

export interface Evidence {
  _id: string;
  counterpartId: string;
  type: string;
  content: string;
  source: string;
  reliability: number;
}

export interface CounterpartContext {
  counterpart: Counterpart;
  activeTraits: Trait[];
  evidence: Evidence[];
}

export class BackendError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "BackendError";
  }
}

/** Frontend uses `dana-reyes`; Mongo `_id`s use `dana_reyes`. */
export function toCounterpartId(personaId: string): string {
  return personaId.replace(/-/g, "_");
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new BackendError(`Backend unreachable at ${BASE}`, 503);
  }

  if (!res.ok) {
    const detail = await res.json().catch(() => ({ error: res.statusText }));
    throw new BackendError(detail.error || `Backend ${res.status}`, res.status);
  }

  return res.json() as Promise<T>;
}

/**
 * Passes a browser request straight through to the backend and streams the
 * response back unchanged (status, headers, body). Used for the routes whose
 * logic lives entirely in FastAPI: chat turns, speech, persona creation.
 */
export async function forward(path: string, request: Request): Promise<Response> {
  try {
    const upstream = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      // If the browser cancels (barge-in), cancel the backend call too.
      signal: request.signal,
      cache: "no-store",
    });
    const headers = new Headers();
    for (const name of ["content-type", "cache-control", "x-delivery"]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch (err) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    console.error(`[backend] ${path}`, err);
    return Response.json({ error: `Backend unreachable at ${BASE}` }, { status: 503 });
  }
}

export function listCounterparts(): Promise<{ counterparts: CounterpartSummary[] }> {
  return call("/api/counterparts");
}

export function getContext(counterpartId: string): Promise<CounterpartContext> {
  return call(`/api/counterparts/${counterpartId}/context`);
}
