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
  stats: { parts: number; studs_used: number; subs: number; inventory_remaining: number };
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

export type TapeActor = "designer" | "inspector" | "repair" | "scribe" | "router";
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
  topple_margin: number;
  sturdiness: number;
  weakest_layer: number | null;
  failures: { code: string; human: string }[];
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

const post = (path: string, body: unknown = {}) => request<Payload>(path, { method: "POST", body: JSON.stringify(body) });

export const bricolage = {
  state: () => request<Payload>("/state"),
  ldr: () => request<string>("/ldr"),
  build: (prompt: string) => post("/build", { prompt }),
  edit: (text: string) => post("/edit", { text }),
  tryAnother: () => post("/try_another"),
  undo: () => post("/undo"),
  redo: () => post("/redo"),
  setInventory: (items: { part: string; color: number; count: number }[]) => request<{ ok: boolean; elements: number }>("/inventory", { method: "POST", body: JSON.stringify({ items }) }),

  /** Live build: tape events arrive as they fire; resolves with the final payload. */
  stream(prompt: string, onEvent: (e: TapeEvent) => void): Promise<Payload> {
    return new Promise((resolve, reject) => {
      const es = new EventSource(`${BASE}/build_stream?prompt=${encodeURIComponent(prompt)}`);
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
