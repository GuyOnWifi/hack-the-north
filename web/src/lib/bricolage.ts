// Client for Lane B's API (bricolage/server.py), typed to the contracts in
// HANDOFF.md / fixtures/. Requests go to /bricolage/*, which next.config.ts
// rewrites to BRICOLAGE_URL. When the API is unreachable the frozen fixtures
// in public/bricolage-fixtures stand in, so the demo survives wifi dying.

export interface BricolagePart {
  id: string;
  part: string;
  color: number;
  pos: [number, number, number];
  rot: number;
  sub: string;
}

export interface BricolageBuild {
  id: string;
  version: number;
  name: string;
  parts: BricolagePart[];
}

export interface ReportIssue {
  code: string;
  sub: string | null;
  /** Written as UI copy: render verbatim. */
  human: string;
}

export interface Report {
  ok: boolean;
  errors: ReportIssue[];
  warnings: ReportIssue[];
  stats: { parts: number; studs_used: number; subs: number };
}

export interface BuildStep {
  n: number;
  sub: string;
  layer: number;
  parts: string[];
  /** "part:color" -> count */
  elements: Record<string, number>;
}

export interface Steps {
  build_id: string;
  n_steps: number;
  steps: BuildStep[];
}

export type TapeActor = "router" | "planner" | "designer" | "builder" | "inspector" | "critic" | "repair" | "scribe";
export type TapeStatus = "ok" | "fail" | "warn" | "running";

/** Contract 4: one agent-tape event. */
export interface TapeEvent {
  t: number;
  actor: TapeActor;
  kind: string;
  text: string;
  status: TapeStatus;
  ms: number;
  tokens: number;
}

/** Structural stability of the current build (from Lane B's physics engine). */
export interface Physics {
  stable: boolean;
  com: [number, number] | null;
  base: [number, number][];
  topple_margin?: number;
  sturdiness?: number;
  weakest_layer?: number | null;
  /** Number of stud joints the solver checked (harness builds). */
  studs?: number;
  /** Indices of bricks the force/torque solver couldn't hold — drawn red. */
  broken?: number[];
  failures: { code: string; human: string }[];
}

/** One of the candidate designs, while the run waits for someone to pick. */
export interface Choice {
  n: number;
  /** How this design was asked to differ from the others. */
  style: string;
  stands: boolean;
  image?: string;
  ldr: string;
}

/** A model designed on this machine, kept on disk between sessions. */
export interface SavedModel {
  id: string;
  name: string;
  idea?: string;
  parts?: number;
  score?: number | null;
  stands?: boolean;
  made?: string;
  thumb?: boolean;
}

export interface Payload {
  version: string | null;
  name?: string;
  build?: BricolageBuild;
  report?: Report;
  steps?: Steps | null;
  tape?: TapeEvent[];
  tree?: string;
  head?: string | null;
  physics?: Physics;
}

const BASE = "/bricolage";
const FIXTURES = "/bricolage-fixtures";

// The SSE stream must skip the Next dev proxy (it buffers streaming responses),
// so EventSource talks to the backend origin directly. Override with
// NEXT_PUBLIC_STREAM_ORIGIN; otherwise assume the backend is on :8017 of the
// same host (what run.sh launches). Non-stream REST calls keep using the proxy.
const STREAM_ORIGIN =
  process.env.NEXT_PUBLIC_STREAM_ORIGIN ||
  (typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8017` : "");
const STREAM_BASE = STREAM_ORIGIN ? `${STREAM_ORIGIN}/api` : BASE;

async function request<T>(path: string, init?: RequestInit, timeoutMs = 60000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, { ...init, signal: ctrl.signal, headers: { "Content-Type": "application/json", ...init?.headers } });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(body.error ?? `HTTP ${res.status}`, res.status);
    }
    const type = res.headers.get("content-type") ?? "";
    return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
  ) {
    super(message);
  }
}

const post = (path: string, body: unknown = {}, timeoutMs?: number) => request<Payload>(path, { method: "POST", body: JSON.stringify(body) }, timeoutMs);

// Pipeline C revises a brief for an edit (1-3 min) and redesigns from scratch
// for "try another" (6-10 min), so those calls get room to finish.
const DESIGN_TIMEOUT = 15 * 60 * 1000;

export const bricolage = {
  state: () => request<Payload>("/state"),
  /** Everything designed here, newest first. */
  library: () => request<{ models: SavedModel[] }>("/library"),
  /** A saved model's picture (its front render). */
  thumb: (id: string) => `${BASE}/library/thumb?id=${encodeURIComponent(id)}`,
  /** Make a saved model the current one, so every build screen works on it. */
  open: (id: string) => post("/open", { id }, DESIGN_TIMEOUT),
  ldr: () => request<string>("/ldr"),
  build: (prompt: string) => post("/build", { prompt }),
  edit: (text: string) => post("/edit", { text }, DESIGN_TIMEOUT),
  /** Pick a candidate design mid-run; null hands it back to the critic. */
  choose: (index: number | null, note = "") => request<{ ok: boolean }>("/choose", { method: "POST", body: JSON.stringify({ index, note }) }),
  tryAnother: () => post("/try_another", {}, DESIGN_TIMEOUT),
  undo: () => post("/undo"),
  redo: () => post("/redo"),

  /** Live build: tape events arrive as they fire; resolves with the final payload. */
  stream(prompt: string, onEvent: (e: TapeEvent) => void): Promise<Payload> {
    return new Promise((resolve, reject) => {
      // Connect the SSE stream DIRECTLY to the backend, bypassing the Next dev
      // proxy — that proxy buffers streaming responses for the browser, so live
      // tape events never arrive until the build finishes. The backend sends
      // Access-Control-Allow-Origin:* so cross-origin EventSource is fine.
      const es = new EventSource(`${STREAM_BASE}/build_stream?prompt=${encodeURIComponent(prompt)}`);
      let settled = false;
      const done = (fn: () => void) => {
        if (settled) return;
        settled = true;
        es.close();
        fn();
      };
      es.onmessage = (m) => {
        const data = JSON.parse(m.data);
        if (data.event === "done") done(() => resolve(data as Payload));
        else if (data.event === "error") done(() => reject(new ApiError(data.error ?? "The builder hit an error")));
        else onEvent(data as TapeEvent);
      };
      es.onerror = () => done(() => reject(new ApiError("Lost connection to the builder")));
    });
  },
};

/** The frozen fixtures, shaped like a live payload. */
export async function fixturePayload(): Promise<{ payload: Payload; ldr: string }> {
  const [build, report, steps, ldr, tape] = await Promise.all([
    fetch(`${FIXTURES}/build.json`).then((r) => r.json()),
    fetch(`${FIXTURES}/report.json`).then((r) => r.json()),
    fetch(`${FIXTURES}/steps.json`).then((r) => r.json()),
    fetch(`${FIXTURES}/model.ldr`).then((r) => r.text()),
    fetch(`${FIXTURES}/tape.sse`).then((r) => r.text()),
  ]);
  return { payload: { version: "fixture", name: build.name, build, report, steps, tape: parseSse(tape) }, ldr };
}

export function parseSse(text: string): TapeEvent[] {
  return text
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => JSON.parse(l.slice(5)))
    .filter((e) => e && e.actor);
}
